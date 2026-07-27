from app.services import memory_service as mem


class FakeCollection:
    name = "fake_memory"

    def __init__(self) -> None:
        self.rows = [
            {
                "id": f"id-{index}",
                "document": f"lesson {index}",
                "metadata": {"timestamp": f"2026-01-0{index + 1}T00:00:00+00:00"},
            }
            for index in range(4)
        ]

    def get(self):
        return {
            "ids": [row["id"] for row in self.rows],
            "documents": [row["document"] for row in self.rows],
            "metadatas": [row["metadata"] for row in self.rows],
        }

    def add(self, *, documents, metadatas, ids) -> None:
        self.rows.append({
            "id": ids[0],
            "document": documents[0],
            "metadata": metadatas[0],
        })

    def delete(self, *, ids) -> None:
        removed = set(ids)
        self.rows = [row for row in self.rows if row["id"] not in removed]


def test_compaction_returns_collection_to_exact_cap() -> None:
    collection = FakeCollection()

    mem._summarise_and_evict(collection, 3, collection.name)

    assert len(collection.rows) == 3
    summaries = [
        row for row in collection.rows
        if row["metadata"].get("type") == "memory_summary"
    ]
    assert len(summaries) == 1
    assert summaries[0]["metadata"]["original_count"] == 2
    assert summaries[0]["metadata"]["verified"] is False
