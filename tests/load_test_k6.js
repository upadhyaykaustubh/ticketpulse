import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate } from 'k6/metrics';

export const successfulBookings = new Counter('successful_bookings');
export const rateLimitedRequests = new Counter('rate_limited_requests');
export const soldOutResponses = new Counter('sold_out_responses');
export const successRate = new Rate('success_rate');

export const options = {
  stages: [
    { duration: '5s', target: 50 },   // Warm-up to 50 users
    { duration: '15s', target: 200 }, // HEAVY STRESS: 200 concurrent users blasting requests!
    { duration: '5s', target: 0 },    // Cool-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const url = 'http://nginx/book';
  const payload = JSON.stringify({ quantity: 1 });
  const params = {
    headers: { 'Content-Type': 'application/json' },
  };

  const res = http.post(url, payload, params);

  if (res.status === 201 || res.status === 200) {
    successfulBookings.add(1);
    successRate.add(1);
  } else if (res.status === 429 || res.status === 503) {
    rateLimitedRequests.add(1);
    successRate.add(0);
  } else if (res.status === 409) {
    soldOutResponses.add(1);
    successRate.add(0);
  }

  check(res, {
    'is status expected (201, 429, 503, 409)': (r) =>
      [200, 201, 409, 429, 503].includes(r.status),
  });

  sleep(0.05); // Rapid fire: 50ms interval!
}
