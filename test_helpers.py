from app.vision import clean_title
from app.bot import is_open_request, md_to_html, titles_in, same_title, match_items, providers_line
from app.recommender import watchlist_summary

# Run: python test_helpers.py  (or pytest)


def test_clean_title():
    assert clean_title("Reacher") == "Reacher"
    assert clean_title('  "Breaking Bad".\n') == "Breaking Bad"
    assert clean_title("“Interstellar”") == "Interstellar"
    assert clean_title("I Am Legend") == "I Am Legend"
    assert clean_title("I, Robot") == "I, Robot"
    assert clean_title("Dark\nIt's a German series.") == "Dark"
    for bad in ["UNKNOWN", "Unknown.", '"UNKNOWN"', "Answer: UNKNOWN", "", None, "   ",
                "I cannot identify the movie from these frames.",
                "Sorry, I'm not able to tell.", "x" * 81]:
        assert clean_title(bad) == "UNKNOWN", bad


def test_is_open_request():
    for text in ["recommend", "What should I watch?", "suggest something", "recommend me a movie please"]:
        assert is_open_request(text), text
    for text in ["Hmm recommend some comedy sitcoms", "suggest something like Dark", "recommend a thriller"]:
        assert not is_open_request(text), text


def test_md_to_html():
    assert md_to_html("1. **Severance** (TV)") == "1. <b>Severance</b> (TV)"
    assert md_to_html("crushed *Dark* (all 26)") == "crushed <i>Dark</i> (all 26)"
    assert md_to_html("**_Black-ish_**") == "<b><i>Black-ish</i></b>"
    assert md_to_html("Tom & Jerry <3") == "Tom &amp; Jerry &lt;3"
    assert md_to_html("5 * 3 = 15, rated 2*") == "5 * 3 = 15, rated 2*"


def test_titles_in():
    reply = ("1. **The Neighborhood** – fits.\n**Why it fits your description:**\n* **Black Family:** Cal\n"
             "2. **Black-ish** – similar. Also **the neighborhood** again.\n3. **Abbott Elementary**\n4. **Barry**")
    assert titles_in(reply) == ["The Neighborhood", "Why it fits your description", "Black Family",
                                "Black-ish", "Abbott Elementary", "Barry"]
    assert titles_in("no titles here") == []
    assert titles_in("**_Modern Family_** and **_The Conners_**") == ["Modern Family", "The Conners"]
    assert titles_in("*   **Ted Lasso:** Heartwarming") == ["Ted Lasso"]
    assert titles_in("**Brooklyn Nine‑Nine** and **Schitt’s Creek**") == ["Brooklyn Nine-Nine", "Schitt's Creek"]


def test_same_title():
    assert same_title("black-ish", "Black-ish")
    assert same_title("Spider-Man: Into the Spider-Verse", "Spider-Man Into the Spider-Verse")
    assert not same_title("A Modern Family", "Modern Family")


def test_match_items():
    items = [{"title": "The Dark Knight"}, {"title": "Dark"}, {"title": "Dark Matter"}, {"title": "Reacher"}]
    assert match_items(items, "dark") == [{"title": "Dark"}]  # exact beats substring
    assert [i["title"] for i in match_items(items, "dark m")] == ["Dark Matter"]
    assert [i["title"] for i in match_items(items, "knight")] == ["The Dark Knight"]
    assert len(match_items([{"title": "Dark Matter"}, {"title": "The Dark Knight"}], "dark")) == 2  # ask which
    assert match_items(items, "severance") == []


def test_providers_line():
    p = lambda *names: [{"provider_name": n} for n in names]
    assert providers_line({"flatrate": p("Netflix", "Prime Video"), "ads": p("Netflix", "MX Player")}) == \
        "📺 Netflix, Prime Video, MX Player"
    assert providers_line({"rent": p("Apple TV"), "buy": p("Apple TV", "Google Play")}) == "💳 Rent/buy: Apple TV, Google Play"
    assert providers_line({"flatrate": p("Amazon Prime Video", "Apple TV", "Apple TV Amazon Channel"),
                           "ads": p("Amazon Prime Video with Ads")}) == "📺 Amazon Prime Video, Apple TV"
    assert providers_line({}) == ""


def test_watchlist_summary():
    items = [
        {"title": "Old", "type": "movie", "status": "completed", "added_at": "2026-01-01"},
        {"title": "Dark", "type": "tv", "status": "watching", "episodes_watched": 12, "last_updated": "2026-10-01"},
    ]
    assert watchlist_summary(items) == "- Dark (tv): watching, ep 12\n- Old (movie): completed"
    assert watchlist_summary(items, limit=1) == "- Dark (tv): watching, ep 12\n(+1 older titles)"
    assert watchlist_summary([]) == "Empty watchlist"


if __name__ == "__main__":
    test_clean_title()
    test_is_open_request()
    test_md_to_html()
    test_titles_in()
    test_same_title()
    test_match_items()
    test_providers_line()
    test_watchlist_summary()
    print("ok")
