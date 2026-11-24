"""Resource-only history: never accepts, reuses or changes scientific results."""
from pathlib import Path
from contextlib import closing
from dataclasses import dataclass
import hashlib, json, math, re, sqlite3
from foundation import owned, read_json, sha, digest
import output_storage


class CaseInputError(ValueError):
    """This particular frozen input could not be verified."""


def initial_budget():
    return dict(reserved_gib=.75, reserved_commit_gib=.75, reference_peak_gib=None,
                reference_commit_gib=None, used_samples=0, legacy_peak=False, family_samples=0,
                configuration_samples=0, observed_family_peak_gib=None, basis='no_history',
                unseen_configuration=True)


def fingerprint(record, plan, case, model):
    building = record['factors']['building']
    # Some buildings are model families with a separate prepared model per case.
    # Use only observations of that exact verified input when no shared snapshot exists.
    has_snapshot = 'model_snapshot' in building
    source = building['model_snapshot'].get('sha256') if has_snapshot else case.get('model_sha256')
    if not building.get('id') or not re.fullmatch('[0-9a-f]{64}', str(source)):
        raise ValueError('缺少已核实的建筑模型来源。')
    engine = plan.get('engine_files', {})
    # Include the runtime libraries, not just the launcher executable. Relocation
    # alone changes no resource family; a different runtime file does.
    family_inputs = dict(building=building['id'], zones=building['zones'], engine_files=sorted(engine.values()))
    family_inputs['source' if has_snapshot else 'prepared_model'] = source
    family = digest(family_inputs)
    shape = {kind: len(items) for kind, items in model.items() if isinstance(items, dict)}
    if case.get('schedule_sharing'):
        family = digest([family, 'shared_file_schedules_v1', shape['Schedule:File']])
    configuration = dict(family=family, mode=case['mode'], period=case['period'],
        step_minutes=case['step_minutes'], output_contract=plan.get('output_contract', 'monthly_period_v1'),
        objects=shape, algorithms={k: model.get(k, {}) for k in ('HeatBalanceAlgorithm',
            'ZoneAirHeatBalanceAlgorithm', 'SurfaceConvectionAlgorithm:Inside', 'SurfaceConvectionAlgorithm:Outside')},
        program_lines=sum(len(v.get('lines', [])) for v in model.get('EnergyManagementSystem:Program', {}).values()),
        output_frequencies=sorted(v.get('reporting_frequency', '') for v in model.get('Output:Variable', {}).values()))
    timing = digest([family, case['mode'], case['step_minutes'], configuration['output_contract'],
                     len(model.get('Schedule:File', {}))])
    workload = digest([timing, case['period'], len(model.get('SurfaceProperty:HeatTransferAlgorithm', {}))])
    return dict(family=family, configuration=digest(configuration), timing=timing, workload=workload)


@dataclass(frozen=True)
class Sample:
    artifact: str
    family: str
    configuration: str
    peak_gib: float
    timing: str = ''
    workload: str = ''
    working: float | None = None
    committed: float | None = None


def valid_peak(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


class History:
    def __init__(self):
        self.samples = {}

    def add(self, sample):
        if not valid_peak(sample.peak_gib):
            return False
        previous = self.samples.get(sample.artifact)
        if previous:
            if previous != sample:
                raise ValueError('同一内存观测的来源或数值冲突。')
            return False
        self.samples[sample.artifact] = sample
        return True

    def estimate(self, key):
        family = [s for s in self.samples.values() if s.family == key['family']]
        if not family:
            return initial_budget()
        exact = [s for s in family if s.configuration == key['configuration']]
        comparable = [s for s in family if s.workload and s.workload == key.get('workload')]
        same_step = [s for s in family if s.timing and s.timing == key.get('timing')]
        used = exact or comparable or same_step or family
        working = max((s.working or s.peak_gib for s in used), default=0.)
        committed = max((s.committed or s.peak_gib for s in used), default=0.)
        return dict(reserved_gib=max(.75, working * 1.25 + .05),
            reserved_commit_gib=max(.75, committed * 1.25 + .05),
            reference_peak_gib=working or None, reference_commit_gib=committed or None,
            used_samples=len(used), legacy_peak=any(not s.working or not s.committed for s in used),
            family_samples=len(family),configuration_samples=len(exact),
            observed_family_peak_gib=max((s.peak_gib for s in family),default=None),
            basis='exact' if exact else 'comparable' if comparable else 'same_step' if same_step else 'family',
            unseen_configuration=not exact)


def startup_wait_seconds(running, now_seconds, settle_seconds=60):
    return max((max(0., settle_seconds - max(0., now_seconds - r['started_seconds']))
                for r in running if r.get('unseen_configuration', True)), default=0.)


class CheckedFiles:
    """Keep small file identities, never retain all model trees in memory."""
    def __init__(self):
        self.files = {}
        self.hash_reads = 0

    @staticmethod
    def stamp(path):
        s = Path(path).stat()
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

    def check(self, path, expected):
        path = str(Path(path).resolve())
        before = self.stamp(path)
        previous = self.files.get(path)
        if previous and previous[0] == before:
            actual = previous[1]
        else:
            actual = sha(path)
            self.hash_reads += 1
            if before != self.stamp(path):
                raise ValueError('读取内存观测来源时文件变化。')
            self.files[path] = before, actual
        if actual != expected:
            raise ValueError('文件内容校验不一致：'+path)
        return path, before, expected


class ResourceHistory:
    def __init__(self, root, progress=None):
        self.root = Path(root).resolve()
        self.folder = self.root / 'data/execution'
        self.files = CheckedFiles()
        self.contexts = {}
        self.history = History()
        self.skipped = 0
        self.progress = progress
        self.refresh()

    def db(self):
        db = sqlite3.connect((self.folder / 'queue.sqlite').as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        return closing(db)

    def context(self, batch, index):
        try:
            return self._context(batch,index)
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise CaseInputError('输入需核查：'+str(error)) from error

    def _context(self, batch, index):
        with self.db() as db:
            row = db.execute('select plan,checksum,review from batches where id=?', (batch,)).fetchone()
        if not row:
            raise ValueError('待计算清单不存在。')
        memo_key = batch, index, row['checksum'], row['plan']
        memo = self.contexts.get(memo_key)
        if memo and all(self.files.stamp(p) == stamp for p, stamp, _ in memo['proofs']):
            return memo
        proofs = []
        def check(path, expected):
            proofs.append(self.files.check(path, expected))
        review = row['review']
        if not re.fullmatch(r'review_[a-f0-9]{32}', review):
            raise ValueError('计算清单标识不正确。')
        folder = owned(self.folder / 'reviews' / review, self.root)
        check(folder / 'plan.json', row['checksum'])
        plan = read_json(folder / 'plan.json')
        if plan != json.loads(row['plan']) or plan['id'] != review:
            raise ValueError('计算清单与登记不一致。')
        case = plan['cases'][index]
        record_path = folder / 'record.json'
        record_stamp = self.files.stamp(record_path)
        record = read_json(record_path)
        if digest(record) != plan['record_sha256']:
            raise ValueError('方案快照变化。')
        if record_stamp != self.files.stamp(record_path):
            raise ValueError('读取期间方案快照变化。')
        check(record_path, sha(record_path))
        if record_stamp != proofs[-1][1]:
            raise ValueError('校验期间方案快照变化。')
        model_path = owned(folder / case['model_file'], folder)
        check(model_path, case['model_sha256'])
        model = read_json(model_path)
        building = record['factors']['building']
        if building.get('zones') is not None and building['zones'] != len(model.get('Zone', {})):
            raise ValueError('建筑房间数量与模型不一致。')
        if 'model_snapshot' in building:
            source = building['model_snapshot']
            if not isinstance(source,dict) or not source.get('path') or not source.get('sha256'):
                raise ValueError('建筑模型快照引用不完整。')
            check(source['path'], source['sha256'])
        if plan['engine'] not in plan['engine_files']:
            raise ValueError('冻结清单缺少计算引擎标识。')
        for path, checksum in plan['engine_files'].items():
            check(path, checksum)
        for path, checksum in case['dependencies'].items():
            check(path, checksum)
        if not all(self.files.stamp(p) == stamp for p, stamp, _ in proofs):
            raise ValueError('读取期间内存分类输入变化。')
        note = None
        try:
            key = fingerprint(record, plan, case, model)
        except Exception as error:
            # Classification is optional. Keep observations of this exact input
            # reusable without pooling unrelated, unrecognized configurations.
            exact = digest({'verified_case':case['identity']})
            key = dict.fromkeys(('family','configuration','timing','workload'),exact)
            note = '仅匹配本算例的历史峰值（'+str(error)+'）'
        memo = dict(key=key, case=case, proofs=proofs, classification_note=note)
        self.contexts[memo_key] = memo
        return memo

    def estimate(self, candidate):
        context = self.context(candidate['batch'], candidate['idx'])
        budget = self.budget_for(context['key'])
        if context['classification_note']:
            budget.setdefault('budget_note',context['classification_note'])
        return dict(budget,key=context['key'],skipped_history=self.skipped)

    def budget_for(self,key):
        try:
            return self.history.estimate(key)
        except Exception as error:
            return dict(initial_budget(),budget_note='历史峰值暂不可用（'+str(error)+'）')

    def refresh(self):
        history = History()
        skipped = 0
        with self.db() as db:
            rows = [dict(r) for r in db.execute("select * from jobs where status in ('passed','review','reused','failed')")]
        if self.progress: self.progress(0, len(rows))
        for index, row in enumerate(rows):
            if self.progress: self.progress(index, len(rows))
            try:
                c = self.context(row['batch'], row['idx'])
                case = c['case']
                if case['identity'] != row['identity']:
                    raise ValueError('计算身份不一致。')
                result = None
                attempt = row['attempt']
                if row['result']:
                    result_path = output_storage.checked_path(row['result'], self.root)
                    self.files.check(result_path, row['result_sha256'])
                    result = read_json(result_path)
                    if result['identity'] != row['identity']:
                        raise ValueError('结果身份不一致。')
                    attempt = result['attempt']
                if not re.fullmatch(r'attempt_[a-f0-9]{32}', str(attempt)):
                    raise ValueError('计算尝试标识不正确。')
                folder = output_storage.attempt_folder(self.root,attempt)
                self.files.check(folder / 'model.epJSON', case['model_sha256'])
                launch = read_json(folder / 'launch.json')
                execution = read_json(folder / 'execution.json')
                if launch['case']['identity'] != case['identity'] or launch['pid'] != execution['pid']:
                    raise ValueError('实际运行与内存观测身份不一致。')
                peak = execution['peak_gib']
                if execution['returncode'] != 0 or not execution.get('finished') or not valid_peak(peak):
                    raise ValueError('缺少完整有效的运行内存观测。')
                if result is not None and result.get('peak_gib') != peak:
                    raise ValueError('结果与实际内存观测不一致。')
                # Reused/accepted copies of one attempt remain one observation.
                working, committed = (execution.get(k) for k in ('peak_working_gib','peak_commit_gib'))
                if not all(valid_peak(v) and v <= peak for v in (working,committed)):
                    working = committed = None
                history.add(Sample(str(folder.resolve()), **c['key'], peak_gib=peak,working=working,committed=committed))
            except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
                skipped += 1
        self.history = history
        self.skipped = skipped
        if self.progress: self.progress(len(rows), len(rows))
        return dict(observations=len(history.samples), skipped=skipped)
