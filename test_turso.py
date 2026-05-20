class TursoRow:
    def __init__(self, fields, values):
        self._fields = fields
        self._values = values
        self._field_map = {f: i for i, f in enumerate(fields)}
        
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        if key in self._field_map:
            return self._values[self._field_map[key]]
        raise KeyError(key)
        
    def get(self, key, default=None):
        if key in self._field_map:
            return self._values[self._field_map[key]]
        return default
        
    def __iter__(self):
        return iter(self._values)
        
    def __len__(self):
        return len(self._values)
        
    def _asdict(self):
        return dict(zip(self._fields, self._values))
        
    def keys(self):
        return self._fields

row = TursoRow(['id', 'name'], [1, 'hello'])
print("row[0]:", row[0])
print("row['name']:", row['name'])
print("dict(row):", dict(row))
print("list(row):", list(row))
print("row.get('name'):", row.get('name'))
