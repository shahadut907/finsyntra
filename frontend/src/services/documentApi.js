/**
 * Document API Service
 * Dedicated service for document CRUD operations with proper authentication
 *
 * SECURITY: Auth is exclusively via httpOnly cookies (credentials: 'include').
 * No tokens are read from localStorage.
 */

import { apiFetch } from '../lib/apiClient';

const documentApi = {
    /**
     * Upload documents with department/role access control
     * @param {File[]} files - Array of files to upload
     * @param {string} department - Target department
     * @param {string|null} targetRole - Target role (null = all roles in department)
     * @param {function} onProgress - Optional progress callback
     */
    uploadDocuments: async (files, department, targetRole = null, onProgress = null) => {
        const formData = new FormData();

        // Append each file
        files.forEach((file) => {
            formData.append('files', file);
        });

        // Append metadata
        formData.append('department', department);
        if (targetRole) {
            formData.append('target_role', targetRole);
        }

        // SECURITY: Use cookie auth only (credentials: 'include').
        // No Bearer header — the httpOnly session_token cookie is sent automatically.
        const response = await apiFetch('/api/admin/upload-department-data', {
            method: 'POST',
            // Don't set Content-Type — browser sets it for FormData with boundary
            body: formData,
        });

        if (!response.ok) {
            const errorText = await response.text();
            let errorMessage;
            try {
                const errorJson = JSON.parse(errorText);
                errorMessage = errorJson.detail || errorJson.message || errorText;
            } catch {
                errorMessage = errorText || `HTTP ${response.status}`;
            }
            throw new Error(errorMessage);
        }

        return await response.json();
    },

    /**
     * List documents (requires auth, RBAC filtered)
     */
    listDocuments: async (params = {}) => {
        const response = await apiFetch('/api/documents/list', {
            method: 'GET',
        });

        if (!response.ok) {
            throw new Error(`Failed to list documents: ${response.status}`);
        }

        return await response.json();
    },

    /**
     * Get document status/statistics
     */
    getDocumentStatus: async () => {
        const response = await apiFetch('/api/documents/status', {
            method: 'GET',
        });

        if (!response.ok) {
            throw new Error(`Failed to get document status: ${response.status}`);
        }

        return await response.json();
    },

    /**
     * Force document refresh (re-index all documents)
     */
    refreshDocuments: async () => {
        const response = await apiFetch('/api/documents/refresh', {
            method: 'POST',
        });

        if (!response.ok) {
            throw new Error(`Failed to refresh documents: ${response.status}`);
        }

        return await response.json();
    },

    /**
     * Admin: Get all documents (from admin endpoint)
     */
    getAdminDocuments: async () => {
        const response = await apiFetch('/api/admin/documents', {
            method: 'GET',
        });

        if (!response.ok) {
            throw new Error(`Failed to get admin documents: ${response.status}`);
        }

        return await response.json();
    },

    /**
     * Validate admin session
     */
    validateSession: async () => {
        const response = await apiFetch('/api/admin/validate-session', {
            method: 'GET',
        });

        return response.ok;
    },
};

export default documentApi;
