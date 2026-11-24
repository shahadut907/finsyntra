import React from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, ExternalLink } from 'lucide-react';

const CorsErrorChip = ({ onRetry, onDismiss }) => {
  const copyBackendCommand = () => {
    const command = `# Add to your backend CORS configuration:
# For FastAPI (Python):
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# For Express.js (Node):
const cors = require('cors');
app.use(cors({
  origin: 'http://localhost:3000',
  methods: ['GET', 'POST', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization']
}));`;

    navigator.clipboard.writeText(command);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-rose-500/10 border border-rose-500/20 rounded-lg p-4 mt-2"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle size={16} className="text-rose-400 mt-0.5 flex-shrink-0" />
        
        <div className="flex-1">
          <div className="text-rose-400 font-medium text-sm mb-2">
            Backend CORS Configuration Required
          </div>
          
          <div className="text-gray-300 text-sm space-y-2">
            <p>
              The backend server needs to allow requests from the frontend (localhost:3000).
            </p>
            
            <div className="bg-black/20 rounded p-2 text-xs font-mono overflow-x-auto">
              <div className="text-gray-400 mb-1"># Backend CORS setup needed:</div>
              <div className="text-finMint">allow_origins: ["http://localhost:3000"]</div>
              <div className="text-finMint">allow_methods: ["GET", "POST", "OPTIONS"]</div>
            </div>
            
            <div className="flex gap-2 mt-3">
              <button
                onClick={copyBackendCommand}
                className="text-xs px-2 py-1 bg-finMint/20 text-finMint rounded hover:bg-finMint/30 transition-colors flex items-center gap-1"
              >
                <ExternalLink size={10} />
                Copy Config
              </button>
              
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="text-xs px-2 py-1 bg-white/10 text-white rounded hover:bg-white/20 transition-colors"
                >
                  Retry
                </button>
              )}
              
              {onDismiss && (
                <button
                  onClick={onDismiss}
                  className="text-xs px-2 py-1 text-gray-400 hover:text-white transition-colors"
                >
                  Dismiss
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

export default CorsErrorChip;
