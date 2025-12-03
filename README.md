# MovieDB+ Demo

Simple MovieDB+ demo application featuring a Flask web front-end, a Redis cache, and
integration with the OMDb API.

## Features

- Search movies via the OMDb API from a simple web interface.
- Cache search responses in Redis for 10 minutes to reduce repeated API calls.
- `/api/search` endpoint returns JSON suitable for API consumption.
- `/api/ratings/summary` aggregates IMDb, Rotten Tomatoes, and Metacritic scores with optional batch input.
- `/api/genres` and `/api/genre/<name>` surface genre metadata with filtering and pagination.
- `/api/boxoffice/top` ranks movies by box office with aggregated ratings and lightweight recommendations.
- Docker Compose setup for the Flask app and Redis cache.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose plugin.
- An OMDb API key. Register for a free key at
  [https://www.omdbapi.com/apikey.aspx](https://www.omdbapi.com/apikey.aspx).

## Getting Started

### 1. Configure Environment Variables

Copy the example environment file and provide your OMDb API key:

```bash
cp .env.example .env
# Edit .env and set OMDB_API_KEY=your_key
```

### 2. Start with Docker Compose

Run the application stack (Flask + Redis) with Docker Compose:

```bash
docker compose up --build
```

The Flask app will be available at [http://localhost:8080](http://localhost:8080).

### 2b. Build the Web Image Manually (Optional)

If you only need the Flask container (for example, when connecting to an
external Redis), build and run the image directly:

```bash
docker build -t moviedb-web .
docker run --env-file .env -p 8080:8080 moviedb-web
```

Adjust `REDIS_HOST`/`REDIS_PORT` in your `.env` file (or pass them with `-e`)
so the container can reach your Redis instance.

### 3. Search for Movies

Open the homepage in your browser, enter a movie title (e.g., “Inception”), and submit the
form. Results are fetched from the OMDb API and cached in Redis for 10 minutes. A cached
response displays instantly on subsequent searches.

You can also hit the API directly:

```
GET http://localhost:8080/api/search?q=Inception
```

### API Examples for Extended Services

- Rating summary for a single movie:  
  `curl "http://localhost:8080/api/ratings/summary?title=Inception"`
- Batch rating summary:  
  `curl -X POST http://localhost:8080/api/ratings/summary -H "Content-Type: application/json" -d "{\"titles\":[\"Inception\",\"Dunkirk\"]}"`
- Genres for a movie:  
  `curl "http://localhost:8080/api/genres?title=Inception"`
- Browse a genre with filters:  
  `curl "http://localhost:8080/api/genre/Action?page=1&rating=7.0&language=English"`
- Top box office ranking (defaults to curated list if no query):  
  `curl "http://localhost:8080/api/boxoffice/top?q=Avengers"`

### 4. Stopping the Stack

Press `Ctrl+C` in the terminal running Docker Compose, then remove containers if desired:

```bash
docker compose down
```

## Local Development (Optional)

If you prefer to run the Flask app without Docker:

1. Create and activate a Python virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Export required environment variables:

   ```bash
   export OMDB_API_KEY=your_key
   export REDIS_HOST=localhost  # or your Redis instance
   export REDIS_PORT=6379
   ```

4. Start the Flask development server:

   ```bash
   flask --app app.py run --port 8080
   ```

Ensure a Redis server is running and reachable at the host/port specified above.
