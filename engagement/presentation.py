from django.db.models import Avg, Count


def rating_summary(reviews):
    aggregate = reviews.aggregate(average=Avg("rating"), total=Count("pk"))
    counts = dict(
        reviews.values("rating").annotate(total=Count("pk")).values_list("rating", "total")
    )
    total = aggregate["total"]
    return {
        "average": aggregate["average"] or 0,
        "total": total,
        "distribution": [
            {
                "rating": value,
                "count": counts.get(value, 0),
                "percent": round(counts.get(value, 0) / total * 100) if total else 0,
            }
            for value in range(5, 0, -1)
        ],
    }
