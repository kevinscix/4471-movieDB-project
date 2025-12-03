# MovieDB Pressure Testing

This directory contains pressure/load testing tools for the MovieDB application.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r tests/requirements.txt
```

Or install directly:
```bash
pip install locust
```

### 2. Start Your Application

Make sure your MovieDB application is running:

```bash
# Using Docker Compose (recommended)
docker-compose up

# Or locally
python app.py
```

The app should be accessible at `http://localhost:8080`

### 3. Run the Pressure Test

**Interactive Mode (with Web UI):**
```bash
locust -f tests/pressure_test.py --host http://localhost:8080
```

Then open http://localhost:8089 in your browser and configure:
- Number of users (start with 10-50)
- Spawn rate (start with 5 users/second)
- Host: http://localhost:8080

**Headless Mode (automated):**
```bash
# Light test: 20 users, 2/sec spawn rate, 30 seconds
locust -f tests/pressure_test.py --host http://localhost:8080 \
    --users 20 --spawn-rate 2 --run-time 30s --headless

# Medium test: 50 users, 5/sec spawn rate, 60 seconds
locust -f tests/pressure_test.py --host http://localhost:8080 \
    --users 50 --spawn-rate 5 --run-time 60s --headless

# Heavy test: 200 users, 10/sec spawn rate, 5 minutes
locust -f tests/pressure_test.py --host http://localhost:8080 \
    --users 200 --spawn-rate 10 --run-time 300s --headless
```

## User Classes

The test includes three user behavior patterns:

### 1. MovieDBUser (Default)
Simulates realistic user behavior with:
- 1-3 seconds wait between requests
- Weighted task distribution (search is most common)
- Mix of different endpoints
- Random query variations

**Usage:**
```bash
locust -f tests/pressure_test.py --host http://localhost:8080
```

### 2. ColdCacheUser
Tests worst-case scenario with uncached requests:
- 0.5-1.5 seconds wait between requests
- Random queries that won't hit cache
- Stresses the OMDb API integration
- Tests timeout and error handling

**Usage:**
```bash
locust -f tests/pressure_test.py --host http://localhost:8080 ColdCacheUser
```

### 3. QuickBurstUser
Rapid-fire stress testing:
- 0.1-0.5 seconds wait between requests
- Tests system under high load
- Validates rate limiting and queueing

**Usage:**
```bash
locust -f tests/pressure_test.py --host http://localhost:8080 QuickBurstUser
```

## Tested Endpoints

The default `MovieDBUser` tests these endpoints with realistic weights:

| Endpoint | Weight | Description |
|----------|--------|-------------|
| `/api/search` | 5x | Movie search (most common action) |
| `/movie/{id}` | 3x | Movie details viewing |
| `/api/genre/{genre}` | 2x | Browse by genre |
| `/api/ratings/summary` | 2x | Rating comparisons |
| `/api/boxoffice/top` | 1x | Box office data (expensive) |
| `/` | 1x | Homepage |

## Understanding the Results

### Key Metrics

**Response Time:**
- **Median (50th percentile)**: Typical user experience
- **95th percentile**: Most users' worst case
- **99th percentile**: Edge cases
- Target: <500ms for cached, <3s for uncached

**Requests per Second (RPS):**
- Total throughput of your application
- Higher is better (with acceptable response times)

**Failure Rate:**
- Should be <1% under normal load
- Watch for timeout errors (OMDb API issues)
- Watch for 500 errors (application issues)

### What to Monitor

1. **Response Times:** Should remain stable as user count increases
2. **Error Rate:** Should stay near 0% for cached requests
3. **Cache Hit Rate:** Check Redis statistics
4. **OMDb API Calls:** Monitor external API usage
5. **System Resources:** CPU, memory, Redis connections

## Testing Scenarios

### Scenario 1: Baseline Performance (Warm Cache)
```bash
# Run once to warm the cache
locust -f tests/pressure_test.py --host http://localhost:8080 \
    --users 10 --spawn-rate 2 --run-time 30s --headless

# Then run the actual test
locust -f tests/pressure_test.py --host http://localhost:8080 \
    --users 50 --spawn-rate 5 --run-time 120s --headless
```
**Expected:** Low response times (<200ms), no errors

### Scenario 2: Cold Cache Stress Test
```bash
# Flush Redis cache first
docker-compose exec redis redis-cli FLUSHALL

# Run the test
locust -f tests/pressure_test.py --host http://localhost:8080 \
    --users 30 --spawn-rate 3 --run-time 60s --headless
```
**Expected:** Higher response times (1-5s), possible timeouts

### Scenario 3: Sustained Load Test
```bash
locust -f tests/pressure_test.py --host http://localhost:8080 \
    --users 100 --spawn-rate 5 --run-time 600s --headless
```
**Expected:** Stable performance over 10 minutes

### Scenario 4: Spike Test
```bash
locust -f tests/pressure_test.py --host http://localhost:8080 \
    --users 200 --spawn-rate 50 --run-time 60s --headless
```
**Expected:** Tests rapid user growth

## Troubleshooting

**High failure rates:**
- Check if the application is running
- Verify OMDb API key is set
- Check Redis connection
- Review application logs

**Slow response times:**
- Check OMDb API rate limits
- Verify Redis is running
- Monitor CPU/memory usage
- Check network latency

**Connection errors:**
- Increase Gunicorn workers in docker-compose.yml
- Check Docker resource limits
- Verify port 8080 is accessible

## Advanced Usage

**Custom CSV reports:**
```bash
locust -f tests/pressure_test.py --host http://localhost:8080 \
    --users 50 --spawn-rate 5 --run-time 120s --headless \
    --csv=results/test_results
```

**HTML report:**
```bash
locust -f tests/pressure_test.py --host http://localhost:8080 \
    --users 50 --spawn-rate 5 --run-time 120s --headless \
    --html=results/report.html
```

**Multiple user classes:**
```bash
# Run both realistic and burst users simultaneously
locust -f tests/pressure_test.py --host http://localhost:8080 \
    MovieDBUser QuickBurstUser
```

## Tips

1. **Start small:** Begin with 10-20 users and gradually increase
2. **Monitor logs:** Watch application and OMDb API logs during tests
3. **Warm the cache:** Run a light test first to populate Redis
4. **Test gradually:** Don't jump straight to 500 users
5. **Check resources:** Monitor Docker stats during tests
6. **Respect APIs:** Be mindful of OMDb API rate limits
7. **Realistic tests:** Use MovieDBUser for production-like scenarios

## Further Reading

- [Locust Documentation](https://docs.locust.io/)
- [Load Testing Best Practices](https://docs.locust.io/en/stable/writing-a-locustfile.html)
