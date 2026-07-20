"""Reusable pagination helper for SQLAlchemy list endpoints."""

import math


def paginate(query, page: int, page_size: int):
    """Apply offset/limit to a SQLAlchemy query.

    Returns:
        (items, paging_meta) where paging_meta is a dict with
        page, page_size, total, total_pages.
    """
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, math.ceil(total / page_size)),
    }
