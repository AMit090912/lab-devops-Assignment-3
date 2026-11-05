// k6 load test for the Lab 3 app
// Run:  k6 run load-testing/k6-load-test.js
//       k6 run -e PROFILE=smoke load-testing/k6-load-test.js
//       k6 run -e PROFILE=stress -e BASE_URL=http://localhost:5000 load-testing/k6-load-test.js
import http from 'k6/http';
import { check, group, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:5000';

const PROFILES = {
  smoke: [{ duration: '30s', target: 5 }],
  load: [
    { duration: '30s', target: 20 },  // ramp up
    { duration: '1m', target: 20 },   // steady
    { duration: '30s', target: 50 },  // peak
    { duration: '30s', target: 0 },   // ramp down
  ],
  stress: [
    { duration: '30s', target: 50 },
    { duration: '1m', target: 100 },
    { duration: '1m', target: 200 },
    { duration: '30s', target: 0 },
  ],
};

export const options = {
  stages: PROFILES[__ENV.PROFILE || 'load'],
  thresholds: {
    http_req_failed: ['rate<0.01'],      // < 1% errors
    http_req_duration: ['p(95)<500'],    // 95% of requests under 500 ms
    checks: ['rate>0.99'],
  },
};

export default function () {
  group('home page', () => {
    const res = http.get(`${BASE_URL}/`);
    check(res, { 'home 200': (r) => r.status === 200 });
  });

  group('list items', () => {
    const res = http.get(`${BASE_URL}/api/items`);
    check(res, { 'list 200': (r) => r.status === 200 });
  });

  group('create item', () => {
    const res = http.post(
      `${BASE_URL}/api/items`,
      JSON.stringify({ name: `k6-vu${__VU}-it${__ITER}` }),
      { headers: { 'Content-Type': 'application/json' } },
    );
    check(res, { 'create 201': (r) => r.status === 201 });
  });

  group('health', () => {
    const res = http.get(`${BASE_URL}/health`);
    check(res, { 'health 200': (r) => r.status === 200 });
  });

  sleep(1);
}
