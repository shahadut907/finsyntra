// Chat API capability detection and management
import { CHAT_URL, CHAT_STREAM_URL, CHAT_STREAM_METHOD, ENABLE_STREAMING, debugChatLog } from '../config/chat';
import { apiFetch } from './apiClient';

// Capability modes
export const CAPABILITY_MODES = {
  SSE_GET: 'sse_get',       // GET with EventSource or fetch stream
  SSE_POST: 'sse_post',     // POST with chunked response stream  
  REST_POST: 'rest_post'    // Regular POST with JSON response
};

// Capability store
class CapabilityStore {
  constructor() {
    this.capabilities = {
      mode: null,
      streamUrl: CHAT_STREAM_URL,
      chatUrl: CHAT_URL,
      detected: false,
      lastProbe: null
    };
    this.probing = false;
  }

  getCapabilities() {
    return { ...this.capabilities };
  }

  setCapabilities(updates) {
    this.capabilities = { ...this.capabilities, ...updates };
    debugChatLog('Capabilities updated:', this.capabilities);
  }

  isDetected() {
    return this.capabilities.detected;
  }

  getMode() {
    return this.capabilities.mode;
  }

  switchMode(newMode, reason = '') {
    debugChatLog(`Switching mode from ${this.capabilities.mode} to ${newMode}`, reason ? `(${reason})` : '');
    this.setCapabilities({ mode: newMode });
  }
}

// Singleton capability store
export const capabilityStore = new CapabilityStore();

// Probe endpoint capabilities
export const probeCapabilities = async () => {
  if (capabilityStore.probing) {
    debugChatLog('Capability probe already in progress, skipping');
    return capabilityStore.getCapabilities();
  }

  capabilityStore.probing = true;

  try {
    debugChatLog('Starting capability detection...');
    
    // If method is explicitly configured, use it
    if (CHAT_STREAM_METHOD) {
      const mode = CHAT_STREAM_METHOD.toUpperCase() === 'GET' 
        ? CAPABILITY_MODES.SSE_GET 
        : CAPABILITY_MODES.SSE_POST;
      
      capabilityStore.setCapabilities({
        mode,
        detected: true,
        lastProbe: new Date()
      });
      
      debugChatLog(`Using configured stream method: ${CHAT_STREAM_METHOD} -> ${mode}`);
      return capabilityStore.getCapabilities();
    }

    // If streaming is disabled, use REST only
    if (!ENABLE_STREAMING) {
      capabilityStore.setCapabilities({
        mode: CAPABILITY_MODES.REST_POST,
        detected: true,
        lastProbe: new Date()
      });
      
      debugChatLog('Streaming disabled, using REST POST mode');
      return capabilityStore.getCapabilities();
    }

    // Probe the stream endpoint with OPTIONS
    try {
      debugChatLog(`Probing OPTIONS ${CHAT_STREAM_URL}`);
      
      const optionsResponse = await fetch(CHAT_STREAM_URL, {
        method: 'OPTIONS',
        headers: {
          'Accept': 'application/json, text/event-stream',
        },
        // Don't include credentials for OPTIONS to avoid auth issues
      });

      debugChatLog(`OPTIONS response: ${optionsResponse.status}`, {
        allow: optionsResponse.headers.get('Allow'),
        contentType: optionsResponse.headers.get('Content-Type'),
        acceptPatch: optionsResponse.headers.get('Accept-Patch')
      });

      if (optionsResponse.ok) {
        const allowHeader = optionsResponse.headers.get('Allow');
        const contentType = optionsResponse.headers.get('Content-Type');
        
        // Check for GET support with SSE hints
        if (allowHeader?.includes('GET') && 
            (contentType?.includes('text/event-stream') || 
             optionsResponse.headers.get('Accept-Patch'))) {
          
          capabilityStore.setCapabilities({
            mode: CAPABILITY_MODES.SSE_GET,
            detected: true,
            lastProbe: new Date()
          });
          
          debugChatLog('Detected GET SSE capability');
          return capabilityStore.getCapabilities();
        }
        
        // Check for POST support
        if (allowHeader?.includes('POST')) {
          capabilityStore.setCapabilities({
            mode: CAPABILITY_MODES.SSE_POST,
            detected: true,
            lastProbe: new Date()
          });
          
          debugChatLog('Detected POST streaming capability');
          return capabilityStore.getCapabilities();
        }
      }
      
      // OPTIONS didn't provide clear guidance, try fallback detection
      debugChatLog('OPTIONS probe inconclusive, trying fallback detection');
      
    } catch (optionsError) {
      debugChatLog('OPTIONS probe failed:', optionsError.message);
      
      // Check if this is a CORS error
      if (optionsError.message?.includes('CORS') || 
          optionsError.message?.includes('blocked') ||
          optionsError.name === 'TypeError' && optionsError.message?.includes('fetch')) {
        debugChatLog('CORS error detected during OPTIONS probe');
        
        // Set REST mode with CORS issue flag
        capabilityStore.setCapabilities({
          mode: CAPABILITY_MODES.REST_POST,
          detected: false,
          lastProbe: new Date(),
          corsIssue: true,
          error: 'Backend CORS policy blocks frontend requests'
        });
        
        return capabilityStore.getCapabilities();
      }
    }

    // Fallback: try a minimal POST to see what happens
    try {
      debugChatLog(`Fallback probe: POST ${CHAT_STREAM_URL}`);
      
      const probeResponse = await apiFetch(CHAT_STREAM_URL, {
        method: 'POST',
        body: JSON.stringify({
          message: '',
          probe: true
        })
      });

      debugChatLog(`Fallback probe response: ${probeResponse.status}`);

      if (probeResponse.status === 405) {
        // Method not allowed on POST, try GET mode
        capabilityStore.setCapabilities({
          mode: CAPABILITY_MODES.SSE_GET,
          detected: true,
          lastProbe: new Date()
        });
        
        debugChatLog('POST returned 405, switching to GET mode');
        return capabilityStore.getCapabilities();
      }
      
      if (probeResponse.ok || probeResponse.status === 400) {
        // Server accepts POST (400 is expected for empty message)
        capabilityStore.setCapabilities({
          mode: CAPABILITY_MODES.SSE_POST,
          detected: true,
          lastProbe: new Date()
        });
        
        debugChatLog('POST probe successful, using POST streaming');
        return capabilityStore.getCapabilities();
      }

    } catch (postError) {
      debugChatLog('POST probe failed:', postError.message);
      
      // Check if this is a CORS error
      if (postError.message?.includes('CORS') || 
          postError.message?.includes('blocked') ||
          postError.name === 'TypeError' && postError.message?.includes('fetch')) {
        debugChatLog('CORS error detected during POST probe');
        
        // Set capabilities with CORS issue flag
        capabilityStore.setCapabilities({
          mode: CAPABILITY_MODES.REST_POST,
          detected: false,
          lastProbe: new Date(),
          corsIssue: true,
          error: 'Backend CORS policy blocks frontend requests'
        });
        
        return capabilityStore.getCapabilities();
      }
    }

    // Final fallback: use REST POST to chat endpoint
    debugChatLog('All streaming probes failed, falling back to REST POST');
    
    capabilityStore.setCapabilities({
      mode: CAPABILITY_MODES.REST_POST,
      detected: true,
      lastProbe: new Date()
    });

    return capabilityStore.getCapabilities();

  } catch (error) {
    debugChatLog('Capability detection failed:', error);
    
    // Emergency fallback
    capabilityStore.setCapabilities({
      mode: CAPABILITY_MODES.REST_POST,
      detected: true,
      lastProbe: new Date()
    });

    return capabilityStore.getCapabilities();
    
  } finally {
    capabilityStore.probing = false;
  }
};

// Handle 405 errors by switching modes
export const handle405Error = async (currentMode, originalUrl) => {
  debugChatLog(`Handling 405 error for mode ${currentMode} on ${originalUrl}`);
  
  if (currentMode === CAPABILITY_MODES.SSE_POST) {
    // POST streaming failed, try GET
    capabilityStore.switchMode(CAPABILITY_MODES.SSE_GET, '405 on POST stream');
    return true; // Indicate retry is possible
  }
  
  if (currentMode === CAPABILITY_MODES.SSE_GET) {
    // GET streaming failed, fall back to REST
    capabilityStore.switchMode(CAPABILITY_MODES.REST_POST, '405 on GET stream');
    return true; // Indicate retry is possible
  }
  
  // Already on REST mode, can't fallback further
  debugChatLog('Already on REST POST mode, cannot fallback further');
  return false;
};

// Initialize capabilities on app start
export const initializeCapabilities = async () => {
  if (capabilityStore.isDetected()) {
    debugChatLog('Capabilities already detected, skipping probe');
    return capabilityStore.getCapabilities();
  }
  
  return await probeCapabilities();
};

// Export store for external access
export { capabilityStore as default };
