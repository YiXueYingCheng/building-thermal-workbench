"""Read-only EnergyPlus observer. Persist one line per complete weather warmup day."""
import json
import math
from pathlib import Path

from pyenergyplus.plugin import EnergyPlusPlugin


class DailyRoomTemperatures(EnergyPlusPlugin):
    def __init__(self):
        super().__init__()
        self.handles = None
        self.environment = None
        self.day = 0
        self.count = 0
        self.disabled = False

    def on_end_of_zone_timestep_after_zone_reporting(self, state):
        exchange = self.api.exchange
        if self.disabled or not exchange.warmup_flag(state):
            return 0
        try:
            # Weather run periods only. Sizing and design days have separate histories.
            if exchange.kind_of_sim(state) == 3 and exchange.api_data_fully_ready(state):
                self.sample(exchange, state)
        except Exception:
            # Diagnostics are optional. A disconnected disk must not fail the simulation.
            self.disabled = True
        return 0

    def sample(self, exchange, state):
        if self.handles is None:
            self.handles = {}
            for name in exchange.get_object_names(state, 'Zone'):
                handle = exchange.get_variable_handle(state, 'Zone Mean Air Temperature', name)
                if handle >= 0:
                    self.handles[name.upper()] = handle
        if not self.handles:
            return
        environment = exchange.current_environment_num(state)
        steps = exchange.num_time_steps_in_hour(state)
        slot = round(exchange.current_time(state) * steps)
        if environment != self.environment:
            self.environment, self.day, self.count = environment, 0, 0
        if slot == 1:
            self.day += 1
            self.count = 0
            self.extrema = {}
        if slot != self.count + 1 or not self.day:
            return
        self.count += 1
        for name, handle in self.handles.items():
            value = exchange.get_variable_value(state, handle)
            if slot == 1:
                self.extrema[name] = [value, value]
            else:
                bounds = self.extrema[name]
                bounds[0] = min(value, bounds[0])
                bounds[1] = max(value, bounds[1])
            if not math.isfinite(value):
                self.extrema[name] = [float('nan'), float('nan')]
        if slot == 24 * steps:
            rooms = {k: v for k, v in self.extrema.items() if all(map(math.isfinite, v))}
            row = dict(env=environment, day=self.day, steps=steps, rooms=rooms)
            with Path('warmup.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, allow_nan=False, separators=(',', ':')) + '\n')

    def on_after_new_environment_warmup_is_complete(self, state):
        if not self.disabled and self.environment == self.api.exchange.current_environment_num(state):
            try:
                with Path('warmup.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(dict(ended=self.environment)) + '\n')
            except OSError:
                pass
            self.disabled = True
        return 0
