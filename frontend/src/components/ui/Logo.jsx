import React from 'react';
import finSolveLogo from '../../assets/finsyntra-logo.png';

const Logo = ({ size = 40, showText = true, className = '' }) => (
    <div className={`finsyntra-logo-container ${className}`} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <img
            src={finSolveLogo}
            alt="FinSyntra AI"
            style={{ width: size, height: size, objectFit: 'contain' }}
        />
        {showText && (
            <span style={{ fontWeight: 700, fontSize: size * 0.45, color: 'var(--color-primary, #0F172A)' }}>
                FinSyntra AI
            </span>
        )}
    </div>
);

export default Logo;
