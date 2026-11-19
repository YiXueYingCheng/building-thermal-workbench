"""Share immutable file schedules in execution copies. Keep the original object names for reporting."""
from collections import defaultdict
from pathlib import Path

from foundation import digest


# Only rewrite fields with known EnergyPlus schedule-reference semantics.
READERS = {
    ('People', 'number_of_people_schedule_name'),
    ('Lights', 'schedule_name'),
    ('ElectricEquipment', 'schedule_name'),
    ('ThermostatSetpoint:SingleHeating', 'setpoint_temperature_schedule_name'),
    ('ThermostatSetpoint:SingleCooling', 'setpoint_temperature_schedule_name'),
    ('ThermostatSetpoint:DualSetpoint', 'heating_setpoint_temperature_schedule_name'),
    ('ThermostatSetpoint:DualSetpoint', 'cooling_setpoint_temperature_schedule_name'),
}


def share_files(model, dependencies, *, trusted_observer=None):
    schedules = model.get('Schedule:File', {})
    if len(schedules) < 2:
        return None
    for kind, objects in model.items():
        if kind.startswith('ExternalInterface'):
            return None
        if kind.startswith('PythonPlugin:') and not (kind == 'PythonPlugin:Instance' and objects == trusted_observer):
            return None
    names = {name.casefold(): name for name in schedules}
    if len(names) != len(schedules):
        return None
    protected = set()
    references = []

    def inspect(kind, obj):
        for field, value in obj.items():
            if isinstance(value, dict):
                inspect(kind, value)
            elif isinstance(value, list):
                for element in value:
                    if isinstance(element, dict):
                        inspect(kind, element)
                    elif isinstance(element, str):
                        protected.add(element.casefold())
            elif isinstance(value, str) and value.casefold() in names:
                key = value.casefold()
                sensor = (kind == 'EnergyManagementSystem:Sensor' and field == 'output_variable_or_output_meter_index_key_name'
                          and obj.get('output_variable_or_output_meter_name', '').casefold() == 'schedule value')
                if sensor or (kind, field) in READERS:
                    references.append((obj, field, names[key]))
                else:
                    # Includes actuators, exact keyed outputs and unfamiliar readers.
                    protected.add(key)

    for kind, objects in model.items():
        if kind == 'Schedule:File':
            continue
        for obj_name, obj in objects.items():
            if kind.startswith('Schedule:') and obj_name.casefold() in names:
                return None
            if kind == 'Output:Variable' and obj.get('variable_name', '').casefold() == 'schedule value':
                key = obj.get('key_value', '*').casefold()
                if key not in ('', '*') and key not in names:
                    # This key may be a regular expression matching several original names.
                    return None
            inspect(kind, obj)
    first = {}
    aliases = {}
    for name in sorted(schedules):
        row = schedules[name]
        if name.casefold() in protected:
            continue
        path = Path(row['file_name']).resolve()
        checksum = dependencies[str(path)]
        signature = checksum, path.suffix.casefold(), digest({k: v for k, v in row.items() if k != 'file_name'})
        kept = first.setdefault(signature, name)
        if kept != name:
            aliases[name] = kept
    if not aliases:
        return None
    for obj, field, original in references:
        if original in aliases:
            obj[field] = aliases[original]
    for name in aliases:
        del schedules[name]
    return dict(version=1, original_count=len(names), retained_count=len(schedules), aliases=aliases)


def aliases_by_source(raw):
    by_source = defaultdict(list)
    for name, source in sorted(raw.get('schedule_sharing', {}).get('aliases', {}).items()):
        by_source[source.upper()].append(name.upper())
    return by_source


def display_dictionary(rows, raw):
    """Negative UI identifiers point to a real SQL series at its original frequency."""
    aliases = aliases_by_source(raw)
    expanded = list(rows)
    alias_id = -1
    for row in rows:
        if row['Name'].casefold() != 'schedule value' or row['IsMeter']:
            continue
        for name in aliases.get(row['KeyValue'].upper(), ()):
            expanded.append(dict(row, KeyValue=name, SharedSchedule=row['KeyValue'],
                                 SourceDictionaryIndex=row['ReportDataDictionaryIndex'], ReportDataDictionaryIndex=alias_id))
            alias_id -= 1
    return expanded
