from sqlalchemy import select
from models import Novel

LANGUAGES = {"mixed": "Mixed", "zh": "Chinese", "ko": "Korean"}
STATUSES = ("ongoing", "completed", "hiatus", "dropped", "cancelled")


def pool_ids(language, difficulty, *, require_activation=True):
    meta = Novel.source_metadata
    page = meta["novelupdates_page"]
    query = select(Novel.id).where(
        Novel.original_language.in_(("zh", "ko")),
        meta["scope_rules_version"].as_string() == "scope-v3",
        page["source"].as_string() == "novelupdates",
        meta["broad_candidate"].as_boolean().is_(True),
    )
    if language != "mixed":
        query = query.where(Novel.original_language == language)
    if difficulty == "normal":
        query = query.where(meta["normal_candidate"].as_boolean().is_(True),
                            page["original_chapters_total"].as_integer() > 0,
                            page["publication_status"].as_string().in_(STATUSES))
        if require_activation:
            query = query.where(Novel.daily_eligible.is_(True))
    return query.order_by(Novel.id)
