from app.vision import clean_title
from app.bot import is_open_request, md_to_html, titles_in, same_title

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


if __name__ == "__main__":
    test_clean_title()
    test_is_open_request()
    test_md_to_html()
    test_titles_in()
    test_same_title()
    print("ok")
