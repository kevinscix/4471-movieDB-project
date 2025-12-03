"""
MovieDB Pressure Test using Locust

This script simulates realistic user behavior on the MovieDB application,
testing various endpoints with different load patterns.

Usage:
    # Web UI mode (interactive dashboard at http://localhost:8089)
    locust -f tests/pressure_test.py --host http://localhost:8080

    # Headless mode (automated test)
    locust -f tests/pressure_test.py --host http://localhost:8080 \
        --users 50 --spawn-rate 5 --run-time 60s --headless

    # High load test
    locust -f tests/pressure_test.py --host http://localhost:8080 \
        --users 200 --spawn-rate 10 --run-time 300s --headless
"""

import random
from locust import HttpUser, task, between


class MovieDBUser(HttpUser):
    """
    Simulates a user browsing the MovieDB application.

    Wait time between requests: 1-3 seconds (simulates realistic user behavior)
    """
    wait_time = between(1, 3)

    # Sample data for realistic testing
    SEARCH_QUERIES = [
        "Avengers",
        "Star Wars",
        "Matrix",
        "Inception",
        "Batman",
        "Spider-Man",
        "Titanic",
        "Godfather",
        "Pulp Fiction",
        "Shawshank",
    ]

    IMDB_IDS = [
        "tt0848228",  # The Avengers
        "tt0468569",  # The Dark Knight
        "tt0137523",  # Fight Club
        "tt0111161",  # Shawshank Redemption
        "tt0068646",  # The Godfather
        "tt0109830",  # Forrest Gump
        "tt0133093",  # The Matrix
        "tt0816692",  # Interstellar
        "tt0110912",  # Pulp Fiction
        "tt1375666",  # Inception
        "tt0167260",  # Lord of the Rings: Return of the King
        "tt0120737",  # Lord of the Rings: Fellowship
        "tt0080684",  # Star Wars: Empire Strikes Back
        "tt0076759",  # Star Wars: A New Hope
        "tt2488496",  # Star Wars: The Force Awakens
    ]

    GENRES = [
        "Action",
        "Comedy",
        "Drama",
        "Horror",
        "Sci-Fi",
        "Thriller",
        "Adventure",
        "Animation",
        "Crime",
        "Fantasy",
        "Romance",
    ]

    @task(5)
    def search_movies(self):
        """
        Test the search API endpoint.
        Weight: 5 (most common user action)
        """
        query = random.choice(self.SEARCH_QUERIES)
        params = {
            "q": query,
            "page": random.randint(1, 3),
            "per_page": 10,
        }

        # Randomly add optional filters (30% chance)
        if random.random() < 0.3:
            params["type"] = random.choice(["movie", "series"])

        if random.random() < 0.2:
            params["year"] = random.randint(1990, 2024)

        with self.client.get(
            "/api/search",
            params=params,
            catch_response=True,
            name="/api/search"
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "results" in data:
                    response.success()
                else:
                    response.failure(f"No results in response: {data}")
            else:
                response.failure(f"Got status {response.status_code}")

    @task(3)
    def view_movie_details(self):
        """
        Test the movie details endpoint.
        Weight: 3 (common action after search)
        """
        imdb_id = random.choice(self.IMDB_IDS)

        with self.client.get(
            f"/movie/{imdb_id}",
            catch_response=True,
            name="/movie/[id]"
        ) as response:
            if response.status_code == 200:
                data = response.json()
                # Check for the correct response structure
                if "movie" in data and isinstance(data["movie"], dict):
                    response.success()
                else:
                    response.failure(f"Invalid movie data structure: {data}")
            else:
                response.failure(f"Got status {response.status_code}")

    @task(2)
    def browse_by_genre(self):
        """
        Test the genre browsing endpoint.
        Weight: 2 (moderate usage)
        """
        genre = random.choice(self.GENRES)
        params = {
            "page": random.randint(1, 3),
        }

        # Randomly add filters (40% chance)
        if random.random() < 0.4:
            params["sort"] = random.choice([
                "rating_desc",
                "year_desc",
                "title_asc"
            ])

        if random.random() < 0.2:
            params["year"] = random.randint(2000, 2024)

        with self.client.get(
            f"/api/genre/{genre}",
            params=params,
            catch_response=True,
            name="/api/genre/[genre]"
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "results" in data:
                    response.success()
                else:
                    response.failure(f"No results in response: {data}")
            else:
                response.failure(f"Got status {response.status_code}")

    @task(2)
    def check_ratings(self):
        """
        Test the ratings summary endpoint.
        Weight: 2 (moderate usage)
        """
        # Test GET method with single ID
        # Note: The endpoint only accepts single 'id' parameter for GET requests
        # For multiple IDs, use POST method with JSON body
        imdb_id = random.choice(self.IMDB_IDS)

        params = {
            "id": imdb_id
        }

        with self.client.get(
            "/api/ratings/summary",
            params=params,
            catch_response=True,
            name="/api/ratings/summary (GET)"
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "results" in data and isinstance(data["results"], list):
                    response.success()
                else:
                    response.failure(f"Unexpected response format: {data}")
            else:
                response.failure(f"Got status {response.status_code}")

    @task(1)
    def view_box_office(self):
        """
        Test the box office endpoint.
        Weight: 1 (less common, more resource-intensive)
        """
        params = {
            "page": 1,
            "per_page": 10,
        }

        # Randomly add filters (30% chance)
        if random.random() < 0.3:
            params["genre"] = random.choice(self.GENRES)

        if random.random() < 0.3:
            params["sort"] = random.choice([
                "box_office_desc",
                "rating_desc"
            ])

        with self.client.get(
            "/api/boxoffice/top",
            params=params,
            catch_response=True,
            name="/api/boxoffice/top"
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "results" in data or "movies" in data:
                    response.success()
                else:
                    response.failure(f"No results in response: {data}")
            else:
                response.failure(f"Got status {response.status_code}")

    @task(1)
    def view_homepage(self):
        """
        Test the main homepage.
        Weight: 1 (entry point for users)
        """
        with self.client.get(
            "/",
            catch_response=True,
            name="/"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status {response.status_code}")


class ColdCacheUser(HttpUser):
    """
    Aggressive user that tests uncached requests.

    This simulates worst-case scenario where cache is cold or expired.
    Use this to test OMDb API rate limits and timeout handling.

    To use this user class instead:
        locust -f tests/pressure_test.py --host http://localhost:8080 ColdCacheUser
    """
    wait_time = between(0.5, 1.5)

    # Extended list of valid IMDb IDs for testing
    VALID_IMDB_IDS = [
        "tt0848228",  # The Avengers
        "tt0468569",  # The Dark Knight
        "tt0137523",  # Fight Club
        "tt0111161",  # Shawshank Redemption
        "tt0068646",  # The Godfather
        "tt0109830",  # Forrest Gump
        "tt0133093",  # The Matrix
        "tt0816692",  # Interstellar
        "tt0110912",  # Pulp Fiction
        "tt1375666",  # Inception
        "tt0167260",  # LOTR: Return of the King
        "tt0120737",  # LOTR: Fellowship
        "tt0080684",  # Star Wars: Empire
        "tt0076759",  # Star Wars: New Hope
        "tt2488496",  # Star Wars: Force Awakens
        "tt0167261",  # LOTR: Two Towers
        "tt0099685",  # Goodfellas
        "tt0073486",  # One Flew Over Cuckoo's Nest
        "tt0047478",  # Seven Samurai
        "tt0102926",  # Silence of the Lambs
    ]

    @task
    def random_search(self):
        """Search with random queries to avoid cache hits"""
        query = f"movie{random.randint(1, 10000)}"
        self.client.get(f"/api/search?q={query}", name="/api/search (uncached)")

    @task
    def random_movie(self):
        """Test valid IMDb IDs to verify proper movie detail handling"""
        valid_id = random.choice(self.VALID_IMDB_IDS)
        self.client.get(f"/movie/{valid_id}", name="/movie/[id] (uncached)")


# Performance testing scenarios
class QuickBurstUser(HttpUser):
    """
    Quick burst testing - simulates rapid-fire requests with minimal wait time.

    To use:
        locust -f tests/pressure_test.py --host http://localhost:8080 QuickBurstUser
    """
    wait_time = between(0.1, 0.5)

    @task
    def quick_search(self):
        query = random.choice(["Avengers", "Batman", "Matrix"])
        self.client.get(f"/api/search?q={query}", name="/api/search (burst)")


if __name__ == "__main__":
    print(__doc__)
    print("\n" + "="*70)
    print("Available User Classes:")
    print("  - MovieDBUser (default): Realistic user behavior simulation")
    print("  - ColdCacheUser: Tests with cache misses and uncached data")
    print("  - QuickBurstUser: Rapid-fire requests for stress testing")
    print("="*70)
