
import base64
from typing import List, Optional

import pandas as pd
import requests
import streamlit as st


st.set_page_config(page_title="Artist Spotle", page_icon="🎧", layout="wide")

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

TARGET_ARTIST_NAME = "The Chainsmokers"
MAX_GUESSES = 10
METADATA_FILE = "artists_metadata.csv"


def get_secret(name: str) -> Optional[str]:
    try:
        return st.secrets[name]
    except Exception:
        return None


@st.cache_data(ttl=86400)
def load_metadata() -> pd.DataFrame:
    df = pd.read_csv(METADATA_FILE)
    df["artist_normalized"] = df["artist"].str.lower().str.strip()
    return df


def get_metadata_for_artist(artist_name: str) -> Optional[dict]:
    metadata = load_metadata()
    match = metadata[metadata["artist_normalized"] == artist_name.lower().strip()]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


@st.cache_data(ttl=3300)
def get_spotify_token(client_id: str, client_secret: str) -> str:
    auth_string = f"{client_id}:{client_secret}"
    auth_base64 = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")

    response = requests.post(
        SPOTIFY_TOKEN_URL,
        headers={
            "Authorization": f"Basic {auth_base64}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=15,
    )

    if response.status_code != 200:
        raise RuntimeError(f"Spotify auth failed: {response.status_code} - {response.text}")

    return response.json()["access_token"]


def spotify_get(path: str, token: str, params: Optional[dict] = None) -> dict:
    response = requests.get(
        f"{SPOTIFY_API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=15,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Spotify API error: {response.status_code} - {response.text}\n\n"
            f"Endpoint: {path}\n"
            f"Params: {params}"
        )

    return response.json()


@st.cache_data(ttl=86400)
def search_artists(query: str, client_id: str, client_secret: str) -> List[dict]:
    token = get_spotify_token(client_id, client_secret)
    data = spotify_get(
        "/search",
        token,
        params={"q": query, "type": "artist", "limit": 8},
    )
    return data.get("artists", {}).get("items", [])


@st.cache_data(ttl=86400)
def get_full_artist_by_id(artist_id: str, client_id: str, client_secret: str) -> dict:
    token = get_spotify_token(client_id, client_secret)
    return spotify_get(f"/artists/{artist_id}", token)


@st.cache_data(ttl=86400)
def get_artist_by_name(name: str, client_id: str, client_secret: str) -> Optional[dict]:
    results = search_artists(name, client_id, client_secret)
    if not results:
        return None

    exact = [artist for artist in results if artist["name"].lower() == name.lower()]
    match = exact[0] if exact else results[0]
    return get_full_artist_by_id(match["id"], client_id, client_secret)


def build_artist_record(raw_artist: dict) -> Optional[dict]:
    metadata = get_metadata_for_artist(raw_artist["name"])
    if metadata is None:
        return None

    image_url = raw_artist.get("images", [{}])[0].get("url") if raw_artist.get("images") else None

    return {
        "id": raw_artist["id"],
        "artist": raw_artist["name"],
        "genre": metadata["genre"],
        "country": metadata["country"],
        "artist_type": metadata["artist_type"],
        "gender": metadata["gender"],
        "debut_year": int(metadata["debut_year"]),
        "image_url": image_url,
        "spotify_url": raw_artist.get("external_urls", {}).get("spotify"),
    }


def compare_year(guess_year: int, target_year: int):
    if guess_year == target_year:
        return "correct", "Exact"
    if abs(guess_year - target_year) <= 3:
        return "close", "Target debuted later ⬆️" if guess_year < target_year else "Target debuted earlier ⬇️"
    return "wrong", "Target debuted later ⬆️" if guess_year < target_year else "Target debuted earlier ⬇️"


def compare_field(guess_value, target_value):
    return "correct" if guess_value == target_value else "wrong"


def compare_guess(guess: dict, target: dict) -> dict:
    year_status, year_hint = compare_year(guess["debut_year"], target["debut_year"])

    return {
        "artist": {
            "value": guess["artist"],
            "status": "correct" if guess["id"] == target["id"] else "wrong",
            "hint": "",
        },
        "genre": {
            "value": guess["genre"],
            "status": compare_field(guess["genre"], target["genre"]),
            "hint": "",
        },
        "country": {
            "value": guess["country"],
            "status": compare_field(guess["country"], target["country"]),
            "hint": "",
        },
        "artist_type": {
            "value": guess["artist_type"],
            "status": compare_field(guess["artist_type"], target["artist_type"]),
            "hint": "",
        },
        "gender": {
            "value": guess["gender"],
            "status": compare_field(guess["gender"], target["gender"]),
            "hint": "",
        },
        "debut_year": {
            "value": guess["debut_year"],
            "status": year_status,
            "hint": year_hint,
        },
    }


def cell_style(status):
    colors = {
        "correct": "background-color: #2E7D32; color: white;",
        "close": "background-color: #F9A825; color: black;",
        "wrong": "background-color: #424242; color: white;",
    }
    return colors.get(status, "")


def render_guess_table():
    if not st.session_state.guesses:
        st.info("Start by searching for an artist.")
        return

    rows = []
    styles = []

    for item in st.session_state.guesses:
        guess = item["guess"]
        result = item["result"]

        rows.append({
            "Artist": guess["artist"],
            "Genre": result["genre"]["value"],
            "Country": result["country"]["value"],
            "Type": result["artist_type"]["value"],
            "Gender": result["gender"]["value"],
            "Debut Year": f'{result["debut_year"]["value"]} — {result["debut_year"]["hint"]}',
        })

        styles.append({
            "Artist": cell_style(result["artist"]["status"]),
            "Genre": cell_style(result["genre"]["status"]),
            "Country": cell_style(result["country"]["status"]),
            "Type": cell_style(result["artist_type"]["status"]),
            "Gender": cell_style(result["gender"]["status"]),
            "Debut Year": cell_style(result["debut_year"]["status"]),
        })

    display_df = pd.DataFrame(rows)

    def apply_styles(_):
        return pd.DataFrame(styles, index=display_df.index)

    st.dataframe(display_df.style.apply(apply_styles, axis=None), use_container_width=True, hide_index=True)


def reset_game(target_artist: dict):
    st.session_state.target = target_artist
    st.session_state.guesses = []
    st.session_state.game_over = False
    st.session_state.won = False


st.title("🎧 Artist Spotle")
st.caption("Spotify powers artist search/images. The clue data comes from artists_metadata.csv.")

client_id = get_secret("SPOTIFY_CLIENT_ID")
client_secret = get_secret("SPOTIFY_CLIENT_SECRET")

if not client_id or not client_secret:
    st.error("Missing Spotify credentials.")
    st.markdown(
        """
Add your Spotify credentials to `.streamlit/secrets.toml` locally:

```toml
SPOTIFY_CLIENT_ID = "your_client_id"
SPOTIFY_CLIENT_SECRET = "your_client_secret"
```

For Streamlit Cloud, paste the same values into the app's Secrets settings.
"""
    )
    st.stop()

try:
    target_raw = get_artist_by_name(TARGET_ARTIST_NAME, client_id, client_secret)
    if not target_raw:
        st.error(f"Could not find target artist on Spotify: {TARGET_ARTIST_NAME}")
        st.stop()

    target_artist = build_artist_record(target_raw)
    if not target_artist:
        st.error(f"{TARGET_ARTIST_NAME} is missing from {METADATA_FILE}.")
        st.stop()

except Exception as exc:
    st.error(str(exc))
    st.stop()

if "target" not in st.session_state:
    reset_game(target_artist)

with st.sidebar:
    st.header("Game Settings")
    st.write(f"Target artist: **{TARGET_ARTIST_NAME}**")
    st.write(f"Metadata file: `{METADATA_FILE}`")

    if st.button("Restart game"):
        reset_game(target_artist)
        st.rerun()

    if st.button("Clear Streamlit cache"):
        st.cache_data.clear()
        st.rerun()

    st.header("How clues work")
    st.write(
        """
🟩 Exact match  
🟨 Close debut year  
⬆️ Target year is later  
⬇️ Target year is earlier  
⬛ Not a match
"""
    )

    # with st.expander("Artists available in metadata"):
    #     metadata = load_metadata()
    #     st.dataframe(metadata[["artist", "genre", "country", "artist_type", "gender", "debut_year"]], hide_index=True)

remaining = MAX_GUESSES - len(st.session_state.guesses)
st.subheader(f"Guesses remaining: {remaining}")

guess_query = st.text_input(
    "Search for an artist to guess",
    placeholder="Example: Calvin Harris",
    disabled=st.session_state.game_over,
)

search_results = []

if guess_query and len(guess_query.strip()) >= 2 and not st.session_state.game_over:
    try:
        raw_results = search_artists(guess_query.strip(), client_id, client_secret)
        search_results = [
            artist for artist in raw_results
            if get_metadata_for_artist(artist["name"]) is not None
        ]

        if raw_results and not search_results:
            st.warning("Spotify found artists, but none are in artists_metadata.csv yet. Add the artist to the CSV to make them guessable.")

    except Exception as exc:
        st.warning(str(exc))

if search_results:
    options = {artist["name"]: artist for artist in search_results}
    selected_label = st.selectbox("Select your guess", list(options.keys()))

    if st.button("Submit guess", disabled=st.session_state.game_over):
        raw_search_guess = options[selected_label]
        raw_guess = get_full_artist_by_id(raw_search_guess["id"], client_id, client_secret)
        guess = build_artist_record(raw_guess)

        if guess is None:
            st.warning("That artist is not in artists_metadata.csv yet.")
        else:
            already_guessed = any(g["guess"]["id"] == guess["id"] for g in st.session_state.guesses)

            if already_guessed:
                st.warning("You already guessed that artist.")
            else:
                result = compare_guess(guess, st.session_state.target)
                st.session_state.guesses.append({"guess": guess, "result": result})

                if guess["id"] == st.session_state.target["id"]:
                    st.session_state.game_over = True
                    st.session_state.won = True
                elif len(st.session_state.guesses) >= MAX_GUESSES:
                    st.session_state.game_over = True
                    st.session_state.won = False

                st.rerun()

render_guess_table()

if st.session_state.game_over:
    target = st.session_state.target

    cols = st.columns([1, 3])

    with cols[0]:
        if target["image_url"]:
            st.image(target["image_url"], width=180)

    with cols[1]:
        if st.session_state.won:
            st.success(f"🎉 You got it! The artist was **{target['artist']}**.")
        else:
            st.error(f"Out of guesses! The artist was **{target['artist']}**.")

        if target["spotify_url"]:
            st.link_button("Open on Spotify", target["spotify_url"])

with st.expander("Debug: show target metadata"):
    st.json(st.session_state.target)
