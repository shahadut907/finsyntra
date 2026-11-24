import React, { useState, useEffect } from 'react';
import {
    Shield, FileText, Search, BarChart3, Database, Sparkles, Building2,
    FileSpreadsheet, ArrowUpRight
} from 'lucide-react';
import { getRoleInfo } from '../../lib/utils';
import { apiFetch } from '../../lib/apiClient';
import finsolveLogo from '../../assets/finsyntra-logo.png';

/**
 * Empty-conversation state. The job of this screen is to start a
 * conversation, so the greeting and a handful of compact suggestions lead;
 * account and knowledge-base facts are a single quiet line beneath them.
 * Suggestions only prefill the composer (the owner still presses send).
 */

const SUGGESTIONS = {
    base: [
        { icon: FileText, text: 'Summarize the key points from our latest documents' },
        { icon: Search, text: 'Find policy information on expenses and approvals' }
    ],
    general: [
        { icon: BarChart3, text: 'Which documents can I access with my role?' },
        { icon: Sparkles, text: 'What are the main topics covered in our knowledge base?' }
    ],
    c_level: [
        { icon: BarChart3, text: 'Give me an executive summary of Q4 performance' },
        { icon: Sparkles, text: 'What are the key risks in our current documents?' }
    ],
    finance: [
        { icon: FileSpreadsheet, text: 'Analyze expense trends from uploaded reports' },
        { icon: BarChart3, text: 'Explain the P&L variance from last month' }
    ],
    hr: [
        { icon: FileText, text: 'Find information about employee benefits' },
        { icon: Search, text: 'Search for onboarding documentation' }
    ],
    engineering: [
        { icon: FileText, text: 'Find technical specifications and requirements' },
        { icon: Search, text: 'Search for API documentation' }
    ],
    marketing: [
        { icon: BarChart3, text: 'Show me our campaign performance metrics' },
        { icon: Search, text: 'Find brand guidelines and assets' }
    ]
};

const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
};

const ChatWelcome = ({ user, onPromptSelect }) => {
    const [knowledgeStats, setKnowledgeStats] = useState(null);
    const [loading, setLoading] = useState(true);

    const role = user?.role?.toLowerCase() || 'employee';
    const roleInfo = getRoleInfo(role);

    useEffect(() => {
        let cancelled = false;
        const fetchKnowledgeStats = async () => {
            try {
                const response = await apiFetch('/api/knowledge/stats');
                if (response.ok && !cancelled) {
                    setKnowledgeStats(await response.json());
                }
            } catch (error) {
                console.error('Failed to fetch knowledge stats:', error);
            } finally {
                if (!cancelled) setLoading(false);
            }
        };
        fetchKnowledgeStats();
        return () => {
            cancelled = true;
        };
    }, []);

    // Public-demo identities are named "Demo <Role>" (e.g. "Demo CEO"); greet
    // as "CEO", "Finance", etc. by dropping a leading "Demo" token.
    const rawName = user?.name || user?.email?.split('@')[0] || 'there';
    const nameParts = rawName.trim().split(/\s+/).filter(Boolean);
    if (nameParts.length > 1 && nameParts[0].toLowerCase() === 'demo') {
        nameParts.shift();
    }
    const userName = nameParts.join(' ') || rawName;

    const suggestions = [...SUGGESTIONS.base, ...(SUGGESTIONS[role] || SUGGESTIONS.general)];
    const docCount = knowledgeStats?.total_documents;

    return (
        <div className="fs-welcome">
            <div className="fs-welcome-hero">
                <span className="fs-welcome-mark" aria-hidden="true">
                    <img src={finsolveLogo} alt="" />
                </span>
                <h2 className="fs-welcome-title">
                    {getGreeting()}, <span>{userName}</span>
                </h2>
                <p className="fs-welcome-lede">
                    Ask a question and get answers sourced from your organization&apos;s documents.
                </p>
            </div>

            <section className="fs-suggest" aria-label="Suggested questions">
                <h3 className="fs-section-label fs-suggest-label">Try asking</h3>
                <ul className="fs-suggest-grid">
                    {suggestions.map(({ icon: Icon, text }) => (
                        <li key={text}>
                            <button
                                type="button"
                                className="fs-suggest-card"
                                onClick={() => onPromptSelect(text)}
                            >
                                <span className="fs-icon-tile fs-icon-tile--sm" aria-hidden="true">
                                    <Icon size={16} />
                                </span>
                                <span className="fs-suggest-text">{text}</span>
                                <ArrowUpRight size={14} className="fs-suggest-go" aria-hidden="true" />
                            </button>
                        </li>
                    ))}
                </ul>
            </section>

            <ul className="fs-context" aria-label="Workspace context">
                <li>
                    <Shield size={13} aria-hidden="true" />
                    <span>Signed in as {roleInfo.name}</span>
                </li>
                <li>
                    <Building2 size={13} aria-hidden="true" />
                    <span>Tenant isolated</span>
                </li>
                {!loading && typeof docCount === 'number' && (
                    <li>
                        <Database size={13} aria-hidden="true" />
                        <span>
                            {docCount} {docCount === 1 ? 'document' : 'documents'} indexed
                        </span>
                    </li>
                )}
            </ul>
            <p className="fs-welcome-note">
                Answers cite your indexed documents. Financial figures are retrieved, never generated.
            </p>
        </div>
    );
};

export default ChatWelcome;
