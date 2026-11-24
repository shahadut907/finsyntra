import React, { useState, useEffect } from 'react';
import { StickyNote, Save } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui';
import { cn } from '../../lib/utils';

const ScratchpadWidget = ({ apiCall, addNotification, backendOnline }) => {
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);

  useEffect(() => {
    loadScratchpad();
  }, []);

  useEffect(() => {
    const autoSave = setTimeout(() => {
      if (note && note !== localStorage.getItem('scratchpad-note')) {
        saveScratchpad();
      }
    }, 2000);

    return () => clearTimeout(autoSave);
  }, [note]);

  const loadScratchpad = () => {
    const saved = localStorage.getItem('scratchpad-note');
    if (saved) {
      setNote(saved);
    }
  };

  const saveScratchpad = async () => {
    setSaving(true);
    try {
      localStorage.setItem('scratchpad-note', note);
      setLastSaved(new Date());
      
      if (backendOnline && apiCall) {
        // Try to sync with backend
        await apiCall('/api/notes/scratchpad', {
          method: 'POST',
          body: JSON.stringify({ content: note })
        });
      }
    } catch (error) {
      console.error('Failed to save scratchpad:', error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="w-full">
      <CardHeader className="p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <StickyNote size={16} />
            <CardTitle className="text-sm">Quick Notes</CardTitle>
          </div>
          <button
            onClick={saveScratchpad}
            disabled={saving}
            className="text-muted-foreground hover:text-foreground disabled:opacity-50"
            title="Save Note"
          >
            <Save size={12} />
          </button>
        </div>
      </CardHeader>
      <CardContent className="p-3 pt-0">
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Quick notes and reminders..."
          className="w-full h-20 text-xs bg-background border border-border rounded p-2 resize-none focus:outline-none focus:ring-1 focus:ring-primary"
        />
        {lastSaved && (
          <div className="text-xs text-muted-foreground mt-1">
            Saved {lastSaved.toLocaleTimeString()}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default ScratchpadWidget;
