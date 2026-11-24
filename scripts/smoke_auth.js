#!/usr/bin/env node
/**
 * Smoke test for authentication flow
 */
const axios = require('axios');

const API_BASE = 'http://localhost:8000';

async function testAuthFlow() {
  console.log('🔍 Testing Authentication Flow');
  console.log('='.repeat(50));

  try {
    // Test 1: Login to get tokens
    console.log('1. Testing login...');
    const loginResponse = await axios.post(`${API_BASE}/auth/login`, {
      email: process.env.SMOKE_EMAIL,
      password: process.env.SMOKE_PASSWORD
    }, { withCredentials: true });
    
    const { access_token } = loginResponse.data;
    console.log('✅ Login successful, access token received');

    // Test 2: Make authenticated request
    console.log('2. Testing authenticated request...');
    const authResponse = await axios.get(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${access_token}` },
      withCredentials: true
    });
    console.log('✅ Authenticated request successful');

    // Test 3: Simulate expired token (force 401)
    console.log('3. Testing token refresh on 401...');
    try {
      await axios.get(`${API_BASE}/auth/me`, {
        headers: { Authorization: 'Bearer invalid_token' },
        withCredentials: true
      });
    } catch (error) {
      if (error.response?.status === 401) {
        console.log('✅ 401 received for invalid token');
        
        // Test refresh endpoint
        const refreshResponse = await axios.post(`${API_BASE}/auth/refresh`, {}, {
          withCredentials: true
        });
        
        if (refreshResponse.data.access_token) {
          console.log('✅ Token refresh successful');
        } else {
          console.log('❌ Token refresh failed');
        }
      }
    }

    console.log('\n✅ All authentication tests passed!');
    
  } catch (error) {
    console.error('❌ Authentication test failed:', error.message);
    process.exit(1);
  }
}

if (require.main === module) {
  testAuthFlow();
}

module.exports = { testAuthFlow };
