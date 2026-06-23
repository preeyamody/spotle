
import base64
from typing import List, Optional

import pandas as pd
import requests
import streamlit as st


st.set_page_config(page_title="Spotify Artist Spotle", page_icon="🎧", layout="wide")

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

TARGET_ARTIST_NAME = "The Chainsmokers"
MAX_GUESSES = 10


def get_secret(name: str) -> Optional[str]:
    try:
        return st.secrets[name]
    except Exception:
        return None


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

    # Keep this intentionally simple. Spotify accepts artist search limits from 1 to 50.
    data = spotify_get(
        "/search",
        token,
        params={
            "q": query,
            "type": "artist",
            "limit": 5,
        },
    )

    return data.get("artists", {}).get("items", [])


@st.cache_data(ttl=86400)
def get_artist_by_name(name: str, client_id: str, client_secret: str) -> Optional[dict]:
    results = search_artists(name, client_id, client_secret)
    if not results:
        return None

    exact = [artist for artist in results if artist["name"].lower() == name.lower()]
    return exact[0] if exact else results[0]


def simplify_artist(raw_artist: dict) -> dict:
    followers = raw_artist.get("followers", {}).get("total", 0)
    genres = raw_artist.get("genres", [])
    image_url = raw_artist.get("images", [{}])[0].get("url") if raw_artist.get("images") else None

    return {
        "id": raw_artist["id"],
        "artist": raw_artist["name"],
        "genres": genres,
        "popularity": raw_artist.get("popularity", 0),
        "followers": followers,
        "image_url": image_url,
        "spotify_url": raw_artist.get("external_urls", {}).get("spotify"),
    }


def compare_number(guess_value, target_value, close_threshold, higher_label, lower_label):
    if guess_value is None or target_value is None:
        return "wrong", "Unknown"

    if guess_value == target_value:
        return "correct", "Exact"

    status = "close" if abs(guess_value - target_value) <= close_threshold else "wrong"
    hint = higher_label if guess_value < target_value else lower_label
    return status, hint


def compare_guess(guess: dict, target: dict) -> dict:
    guess_genres = set(guess.get("genres", []))
    target_genres = set(target.get("genres", []))
    shared_genres = sorted(guess_genres.intersection(target_genres))

    if guess["id"] == target["id"]:
        genre_status = "correct"
        genre_hint = "Exact artist"
    elif shared_genres:
        genre_status = "close"
        genre_hint = "Overlap: " + ", ".join(shared_genres[:3])
    else:
        genre_status = "wrong"
        genre_hint = "No overlap"

    popularity_status, popularity_hint = compare_number(
        guess["popularity"],
        target["popularity"],
        close_threshold=10,
        higher_label="Target is more popular ⬆️",
        lower_label="Target is less popular ⬇️",
    )

    followers_status, followers_hint = compare_number(
        guess["followers"],
        target["followers"],
        close_threshold=max(int(target["followers"] * 0.20), 1),
        higher_label="Target has more followers ⬆️",
        lower_label="Target has fewer followers ⬇️",
    )

    return {
        "artist": {
            "value": guess["artist"],
            "status": "correct" if guess["id"] == target["id"] else "wrong",
            "hint": "",
        },
        "genres": {
            "value": ", ".join(guess["genres"][:3]) or "Unknown",
            "status": genre_status,
            "hint": genre_hint,
        },
        "popularity": {
            "value": guess["popularity"],
            "status": popularity_status,
            "hint": popularity_hint,
        },
        "followers": {
            "value": guess["followers"],
            "status": followers_status,
            "hint": followers_hint,
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
            "Genres": f'{result["genres"]["value"]} — {result["genres"]["hint"]}',
            "Popularity": f'{result["popularity"]["value"]} — {result["popularity"]["hint"]}',
            "Followers": f'{result["followers"]["value"]:,} — {result["followers"]["hint"]}',
        })

        styles.append({
            "Artist": cell_style(result["artist"]["status"]),
            "Genres": cell_style(result["genres"]["status"]),
            "Popularity": cell_style(result["popularity"]["status"]),
            "Followers": cell_style(result["followers"]["status"]),
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


st.title("🎧 Spotify Artist Spotle")
st.caption("Guess the mystery artist using Spotify artist metadata.")

client_id = get_secret("SPOTIFY_CLIENT_ID")
client_secret = get_secret("SPOTIFY_CLIENT_SECRET")

if not client_id or not client_secret:
    st.error("Missing Spotify credentials.")
    st.markdown(
        """
Add your Spotify credentials to `.streamlit/secrets.toml`:

```toml
SPOTIFY_CLIENT_ID = "your_client_id"
SPOTIFY_CLIENT_SECRET = "your_client_secret"
```

Then restart Streamlit.
"""
    )
    st.stop()

try:
    target_raw = get_artist_by_name(TARGET_ARTIST_NAME, client_id, client_secret)

    if not target_raw:
        st.error(f"Could not find target artist: {TARGET_ARTIST_NAME}")
        st.stop()

    target_artist = simplify_artist(target_raw)

except Exception as exc:
    st.error(str(exc))
    st.stop()

if "target" not in st.session_state:
    reset_game(target_artist)

with st.sidebar:
    st.header("Game Settings")
    st.write(f"Target artist: **{TARGET_ARTIST_NAME}**")
    st.write("This version avoids Spotify album lookups to prevent the invalid limit error.")

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
🟨 Close / partial match  
⬆️ Target value is higher  
⬇️ Target value is lower  
⬛ Not a match
"""
    )

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
        search_results = search_artists(
            guess_query.strip(),
            client_id,
            client_secret,
        )
    except Exception as exc:
        st.warning(str(exc))

if search_results:
    options = {
        f'{artist["name"]} — popularity {artist.get("popularity", 0)}': artist
        for artist in search_results
    }

    selected_label = st.selectbox("Select your guess", list(options.keys()))

    if st.button("Submit guess", disabled=st.session_state.game_over):
        raw_guess = options[selected_label]
        guess = simplify_artist(raw_guess)

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
