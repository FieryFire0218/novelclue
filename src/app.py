from datetime import UTC, date, datetime
from hashlib import sha256
from secrets import choice

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from answer_pools import LANGUAGES, pool_ids
from compare import compare_guess, _normalize_rating_5, _round_to_half, _text_key
from database import SessionLocal
from models import DailyAnswer, LanguageDailyAnswer, Novel
from novel_metadata import game_data, snapshot_data

from story_hints import story_hints

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024


@app.get("/health")
def health():
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        app.logger.exception("Database health check failed")
        return jsonify(status="unavailable"), 503
    return jsonify(status="ok")


def options():
    lang = request.args.get("language", "mixed")
    difficulty = request.args.get("difficulty", "normal")
    if lang not in LANGUAGES or difficulty not in ("normal", "hard"):
        abort(400, "Invalid language or difficulty.")
    today = datetime.now(UTC).date()
    try:
        day = date.fromisoformat(request.args.get("day", today.isoformat()))
    except ValueError:
        abort(400, "Invalid puzzle date.")
    if day > today:
        abort(400, "Choose today or a saved puzzle date.")
    return lang, difficulty, day


def archive_query(language):
    if language == "mixed":
        return select(DailyAnswer.day)
    return select(LanguageDailyAnswer.day).where(LanguageDailyAnswer.language == language)


def daily(session, lang, day):
    model = DailyAnswer if lang == "mixed" else LanguageDailyAnswer
    key = {"day": day}
    if lang != "mixed":
        key["language"] = lang
    saved = session.get(model, key)
    if saved is None:
        if day != datetime.now(UTC).date():
            abort(404, "There is no saved puzzle for this language and date.")
        ids = list(session.scalars(pool_ids(lang, "normal")))
        if not ids:
            abort(503, "No active daily answers for this language. Run pool setup.")
        # rotate through a stable shuffle so adjacent database IDs do not dominate a week.
        ids.sort(key=lambda n: sha256(f"daily/{lang}/{n}".encode()).digest())
        novel = session.get(Novel, ids[day.toordinal() % len(ids)])
        snapshot = dict(game_data(novel), hints=story_hints(novel))
        statement = pg_insert(model).values(**key, novel_id=novel.id, answer_data=snapshot)
        session.execute(statement.on_conflict_do_nothing(index_elements=list(key)))
        saved = session.get(model, key)
    answer = snapshot_data(saved.answer_data)
    if "hints" not in answer:
        answer["hints"] = story_hints(session.get(Novel, saved.novel_id))
    return answer


def round_key(lang, novel_id):
    return sha256(f"hard/{lang}/{novel_id}".encode()).hexdigest()[:24]


def answer_for(session, lang, difficulty, day):
    if difficulty == "normal":
        return daily(session, lang, day)
    token = request.args.get("round")
    for novel_id in session.scalars(pool_ids(lang, "hard")):
        if round_key(lang, novel_id) == token:
            novel = session.get(Novel, novel_id)
            return dict(game_data(novel), hints=story_hints(novel))
    abort(404, "This hard round is unavailable. Start a new round.")


def title_list(lang):
    query = select(Novel.id, Novel.title).order_by(Novel.title)
    if lang != "mixed":
        query = query.where(Novel.original_language == lang)
    return query


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(503)
def game_error(error):
    if request.path in ("/guess", "/answer", "/hint"):
        return jsonify(error=error.description), error.code
    return render_template("puzzle_error.html", message=error.description), error.code


@app.get("/")
def index():
    lang, difficulty, day = options()
    with SessionLocal.begin() as session:
        if difficulty == "hard" and not request.args.get("round"):
            ids = list(session.scalars(pool_ids(lang, "hard")))
            if not ids:
                abort(503, "No hard answers available for this language.")
            previous = request.args.get("previous")
            choices = [n for n in ids if round_key(lang, n) != previous] or ids
            return redirect(url_for("index", language=lang, difficulty="hard",
                                    round=round_key(lang, choice(choices))))
        answer_for(session, lang, difficulty, day)
        params = dict(language=lang, difficulty=difficulty)
        if difficulty == "normal":
            params["day"] = day.isoformat()
        else:
            params["round"] = request.args["round"]
        titles = [row.title for row in session.execute(title_list(lang))]
        dates = sorted(session.scalars(archive_query(lang)), reverse=True) if difficulty == "normal" else []
        return render_template("index.html", novels=titles, params=params, lang=lang, difficulty=difficulty,
                               languages=LANGUAGES, day=day, dates=dates)


@app.post("/guess")
def guess():
    lang, difficulty, day = options()
    data = request.get_json(silent=True)
    title = data.get("title") if isinstance(data, dict) else None
    if not isinstance(title, str) or not title.strip():
        abort(400, "Enter a novel title.")
    with SessionLocal.begin() as session:
        candidates = session.execute(title_list(lang))
        key = _text_key(title)
        nid = next((row.id for row in candidates if _text_key(row.title) == key), None)
        if nid is None:
            abort(400, "Novel not found in this language.")
        answer = answer_for(session, lang, difficulty, day)
        return jsonify(compare_guess(game_data(session.get(Novel, nid)), answer))


@app.get("/hint")
def get_hint():
    with SessionLocal.begin() as session:
        return jsonify(hints=answer_for(session, *options())["hints"])


@app.get("/answer")
def get_answer():
    with SessionLocal.begin() as session:
        answer = answer_for(session, *options())
    fields = ("title", "author", "genres", "rating", "chapters", "original_chapters_total",
              "original_chapters_main", "original_chapters_extra", "publication_status", "main_publication_status")
    result = {k: answer.get(k) for k in fields}
    rating = _normalize_rating_5(result["rating"])
    result["rating5"] = None if rating is None else max(0, min(5, _round_to_half(rating)))
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=False)
