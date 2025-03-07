from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import requests
import os
import base64

load_dotenv()

app = FastAPI()

# Updated CORS middleware configuration
origins = [
    "https://spotify-twitter-recap.vercel.app",  # Next.js frontend
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")

@app.post("/refresh-token")
async def refresh_token(request: Request):
    try:
        data = await request.json()
        refresh_token = data.get("refresh_token")
        
        if not refresh_token:
            raise HTTPException(status_code=400, detail="Refresh token is required")
            
        # Prepare the request to Spotify API
        auth_string = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
        auth_bytes = auth_string.encode('ascii')
        auth_header = base64.b64encode(auth_bytes).decode('ascii')
        
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        
        response = requests.post(
            "https://accounts.spotify.com/api/token",
            headers=headers,
            data=payload
        )
        
        if not response.ok:
            print(f"Spotify token refresh failed: {response.status_code} {response.text}")
            raise HTTPException(
                status_code=response.status_code, 
                detail=f"Failed to refresh token: {response.text}"
            )
        
        token_data = response.json()
        
        # Return response with CORS headers
        return JSONResponse(
            content=token_data,
            headers={
                "Access-Control-Allow-Origin": "https://spotify-twitter-recap.vercel.app/",
                "Access-Control-Allow-Credentials": "true",
            }
        )
        
    except Exception as e:
        print(f"Error refreshing token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/recently-played")
async def get_recently_played(access_token: str):
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(
            "https://api.spotify.com/v1/me/player/recently-played",
            headers=headers
        )
        
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Token expired")
            
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Error fetching recently played: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/currently-playing")
async def get_currently_playing(access_token: str):
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(
            "https://api.spotify.com/v1/me/player/currently-playing",
            headers=headers
        )
        
        # If no track is playing, return null
        if response.status_code == 204:
            return JSONResponse(
                content={"is_playing": False, "track": None},
                headers={
                    "Access-Control-Allow-Origin": "https://spotify-twitter-recap.vercel.app/",
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization, Origin"
                }
            )
            
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Token expired")
            
        response.raise_for_status()
        data = response.json()
        
        # Extract relevant track information
        track_data = {
            "is_playing": data.get("is_playing", False),
            "track": {
                "name": data.get("item", {}).get("name"),
                "artists": [artist.get("name") for artist in data.get("item", {}).get("artists", [])],
                "album": {
                    "name": data.get("item", {}).get("album", {}).get("name"),
                    "images": data.get("item", {}).get("album", {}).get("images", [])
                },
                "duration_ms": data.get("item", {}).get("duration_ms"),
                "progress_ms": data.get("progress_ms"),
                "external_url": data.get("item", {}).get("external_urls", {}).get("spotify")
            }
        }
        
        return JSONResponse(
            content=track_data,
            headers={
                "Access-Control-Allow-Origin": "https://spotify-twitter-recap.vercel.app/",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, Origin"
            }
        )

    except requests.exceptions.RequestException as e:
        print(f"Error fetching currently playing: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def get_top_albums(tracks_data):
    """
    Calculate top albums from tracks data by counting occurrences of albums
    and aggregating their information.
    """
    album_stats = {}
    
    # Process each track and count album occurrences
    for track in tracks_data.get('items', []):
        album = track.get('album', {})
        album_id = album.get('id')
        
        if not album_id:
            continue
            
        if album_id not in album_stats:
            album_stats[album_id] = {
                'name': album.get('name'),
                'artists': [artist.get('name') for artist in album.get('artists', [])],
                'images': album.get('images', []),
                'release_date': album.get('release_date'),
                'total_tracks': album.get('total_tracks'),
                'external_url': album.get('external_urls', {}).get('spotify'),
                'count': 0,
                'tracks': []
            }
        
        album_stats[album_id]['count'] += 1
        album_stats[album_id]['tracks'].append({
            'name': track.get('name'),
            'popularity': track.get('popularity')
        })
    
    # Convert to list and sort by count
    top_albums = [
        {**stats, 'id': album_id} 
        for album_id, stats in album_stats.items()
    ]
    top_albums.sort(key=lambda x: x['count'], reverse=True)
    
    return top_albums[:10]  # Return top 10 albums


@app.get("/callback")
async def callback(code: str):
    print(f"Received code from Spotify: {code}")
    
    token_url = "https://accounts.spotify.com/api/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
    }
    auth = (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)

    try:
        # Exchange authorization code for access token
        response = requests.post(token_url, data=payload, auth=auth)
        response.raise_for_status()
        token_data = response.json()
        
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        
        if not access_token or not refresh_token:
            raise HTTPException(status_code=400, detail="Failed to retrieve tokens")

        # Get user profile
        headers = {"Authorization": f"Bearer {access_token}"}
        user_profile = requests.get(
            "https://api.spotify.com/v1/me",
            headers=headers
        ).json()

        short_term_artists = requests.get(
            "https://api.spotify.com/v1/me/top/artists?time_range=short_term&limit=10",
            headers=headers
        ).json()

        # Fetch top artists for medium term (last 6 months)
        medium_term_artists = requests.get(
            "https://api.spotify.com/v1/me/top/artists?time_range=medium_term&limit=10",
            headers=headers
        ).json()

        # Fetch top artists for medium term (last 6 months)
        medium_term_artists_long = requests.get(
            "https://api.spotify.com/v1/me/top/artists?time_range=medium_term&limit=50",
            headers=headers
        ).json()

        # Fetch top artists for long term (several years)
        long_term_artists = requests.get(
            "https://api.spotify.com/v1/me/top/artists?time_range=long_term&limit=10",
            headers=headers
        ).json()

        # Fetch top tracks for short term (last 4 weeks)
        short_term_tracks = requests.get(
            "https://api.spotify.com/v1/me/top/tracks?time_range=short_term&limit=10",
            headers=headers
        ).json()

        # Fetch top tracks for medium term (last 6 months)
        medium_term_tracks = requests.get(
            "https://api.spotify.com/v1/me/top/tracks?time_range=medium_term&limit=10",
            headers=headers
        ).json()

        # Fetch top tracks for long term (several years)
        long_term_tracks = requests.get(
            "https://api.spotify.com/v1/me/top/tracks?time_range=long_term&limit=10",
            headers=headers
        ).json()


        top_albums = {
                "short_term": get_top_albums(short_term_tracks),
                "medium_term": get_top_albums(medium_term_tracks),
                "long_term": get_top_albums(long_term_tracks)
            }

        def get_top_genres(artists_data):
            # Create a dictionary to count genre occurrences
            genre_count = {}
            
            # Go through each artist's genres
            for artist in artists_data.get('items', []):
                for genre in artist.get('genres', []):
                    genre_count[genre] = genre_count.get(genre, 0) + 1
            
            # Sort genres by count and get top 10
            sorted_genres = sorted(genre_count.items(), key=lambda x: x[1], reverse=True)
            return dict(sorted_genres[:10])
        
        short_term_genres = get_top_genres(short_term_artists)
        medium_term_genres = get_top_genres(medium_term_artists)
        long_term_genres = get_top_genres(long_term_artists)

        # Include token info in user data
        user_data = {
            **user_profile,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "short_term": short_term_artists,
            "medium_term": medium_term_artists,
            "long_term": long_term_artists,
            "long_term_tracks": long_term_tracks,
            "medium_term_tracks": medium_term_tracks,
            "medium_term_artists_long": medium_term_artists_long,
            "short_term_tracks": short_term_tracks,
            "top_albums": top_albums,
            "top_genres": {
                "short_term": short_term_genres,
                "medium_term": medium_term_genres,
                "long_term": long_term_genres
            }
        }

        # Return as JSONResponse with explicit CORS headers
        return JSONResponse(
            content=user_data,
            headers={
                "Access-Control-Allow-Origin": "https://spotify-twitter-recap.vercel.app/",
                "Access-Control-Allow-Credentials": "true",
            }
        )

    except requests.exceptions.RequestException as e:
        print(f"Error during token exchange: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error exchanging token: {str(e)}")

@app.get("/login")
async def login():
    try:
        auth_url = (
            "https://accounts.spotify.com/authorize"
            f"?response_type=code"
            f"&client_id={SPOTIFY_CLIENT_ID}"
            f"&redirect_uri={SPOTIFY_REDIRECT_URI}"
            f"&scope=user-read-recently-played user-read-private user-read-email user-top-read user-read-currently-playing"
        )
        return RedirectResponse(url=auth_url)

    except Exception as e:
        print(f"Error during login: {e}")
        raise HTTPException(status_code=500, detail="Error redirecting to Spotify.")
