from __future__ import annotations

from database.seed_synthetic_patients import seed_synthetic_patients


class FakeBatchWriter:
    def __init__(self):
        self.items = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def put_item(self, Item):
        self.items.append(Item)


class FakeTable:
    def __init__(self):
        self.writer = FakeBatchWriter()

    def batch_writer(self):
        return self.writer


def test_seeder_writes_all_generated_synthetic_records():
    table = FakeTable()
    written = seed_synthetic_patients(table, count=100)
    assert written == 700
    assert len(table.writer.items) == 700
