// SUPABASE_URL, SUPABASE_ANON_KEY, and FUNCTION_BASE are defined in index.html

function crmApp() {
  return {
    leads: [],
    selectedLead: null,
    messages: [],
    replyText: '',
    filterStatus: 'all',
    sending: false,
    realtimeConnected: false,
    config: { template_2: '', template_3: '' },
    _channel: null,

    // Template editor
    showTemplates: false,
    templates: [],
    savingTemplate: null,

    statuses: [
      { value: 'all',            label: 'All' },
      { value: 'new',            label: 'New' },
      { value: 'auto_contacted', label: 'Auto-contacted' },
      { value: 'replied',        label: 'Replied' },
      { value: 'booked',         label: 'Booked' },
    ],

    async init() {
      await Promise.all([this.loadConfig(), this.loadLeads()]);
      this.connectRealtime();
    },

    async loadConfig() {
      try {
        const res = await fetch(`${FUNCTION_BASE}/crm-api/config`);
        if (res.ok) this.config = await res.json();
      } catch (e) {
        console.error('Failed to load config:', e);
      }
    },

    async loadLeads() {
      const url = this.filterStatus === 'all'
        ? `${FUNCTION_BASE}/crm-api/leads`
        : `${FUNCTION_BASE}/crm-api/leads?status=${this.filterStatus}`;
      try {
        const res = await fetch(url);
        if (!res.ok) return;
        const fresh = await res.json();
        if (this.selectedLead) {
          const updated = fresh.find(l => l.id === this.selectedLead.id);
          if (updated) this.selectedLead = updated;
        }
        this.leads = fresh;
      } catch (e) {
        console.error('Failed to load leads:', e);
      }
    },

    async selectLead(lead) {
      this.selectedLead = lead;
      this.showTemplates = false;
      this.replyText = '';
      await this.loadMessages(lead.id);
      this.$nextTick(() => this.scrollToBottom());
    },

    closeLead() {
      this.selectedLead = null;
      this.messages = [];
      this.replyText = '';
    },

    async loadMessages(leadId) {
      try {
        const res = await fetch(`${FUNCTION_BASE}/crm-api/leads/${leadId}/messages`);
        if (!res.ok) return;
        this.messages = await res.json();
      } catch (e) {
        console.error('Failed to load messages:', e);
      }
    },

    async sendReply() {
      if (!this.replyText.trim() || this.sending || !this.selectedLead) return;
      this.sending = true;
      const body = this.replyText;
      this.replyText = '';
      try {
        const res = await fetch(`${FUNCTION_BASE}/crm-api/leads/${this.selectedLead.id}/send`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ body }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert('Send failed: ' + (err.error || res.statusText));
          this.replyText = body;
        }
      } catch (e) {
        console.error('Send error:', e);
        this.replyText = body;
      } finally {
        this.sending = false;
      }
    },

    async sendTemplate(n) {
      if (this.sending || !this.selectedLead) return;
      this.sending = true;
      try {
        const res = await fetch(`${FUNCTION_BASE}/crm-api/leads/${this.selectedLead.id}/template/${n}`, {
          method: 'POST',
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert('Template send failed: ' + (err.error || res.statusText));
        }
      } catch (e) {
        console.error('Template send error:', e);
      } finally {
        this.sending = false;
      }
    },

    async deleteLead(leadId) {
      if (!confirm('Delete this lead and all their messages? This cannot be undone.')) return;
      try {
        const res = await fetch(`${FUNCTION_BASE}/crm-api/leads/${leadId}`, { method: 'DELETE' });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert('Delete failed: ' + (err.error || res.statusText));
          return;
        }
        this.closeLead();
        await this.loadLeads();
      } catch (e) {
        console.error('Delete error:', e);
      }
    },

    async updateStatus(leadId, newStatus) {
      try {
        await fetch(`${FUNCTION_BASE}/crm-api/leads/${leadId}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus }),
        });
        await this.loadLeads();
      } catch (e) {
        console.error('Status update failed:', e);
      }
    },

    async openTemplates() {
      this.showTemplates = true;
      this.selectedLead = null;
      try {
        const res = await fetch(`${FUNCTION_BASE}/crm-api/templates`);
        if (res.ok) this.templates = await res.json();
      } catch (e) {
        console.error('Failed to load templates:', e);
      }
    },

    async saveTemplate(tmpl) {
      this.savingTemplate = tmpl.key;
      try {
        const res = await fetch(`${FUNCTION_BASE}/crm-api/templates/${tmpl.key}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ body: tmpl.body }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert('Save failed: ' + (err.error || res.statusText));
        } else {
          await this.loadConfig();
        }
      } catch (e) {
        console.error('Save template error:', e);
      } finally {
        this.savingTemplate = null;
      }
    },

    connectRealtime() {
      const client = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

      if (this._channel) this._channel.unsubscribe();

      this._channel = client
        .channel('crm-changes')
        .on(
          'postgres_changes',
          { event: '*', schema: 'public', table: 'leads' },
          () => { this.loadLeads(); }
        )
        .on(
          'postgres_changes',
          { event: 'INSERT', schema: 'public', table: 'messages' },
          (payload) => {
            const msg = payload.new;
            if (this.selectedLead && msg.lead_id === this.selectedLead.id) {
              const alreadyHave = this.messages.some(m => m.id === msg.id);
              if (!alreadyHave) {
                this.messages.push(msg);
                this.$nextTick(() => this.scrollToBottom());
              }
            }
            this.loadLeads();
          }
        )
        .subscribe((status) => {
          this.realtimeConnected = status === 'SUBSCRIBED';
        });
    },

    scrollToBottom() {
      const el = document.getElementById('chat-messages');
      if (el) el.scrollTop = el.scrollHeight;
    },

    formatTime(iso) {
      const d = new Date(iso);
      const today = new Date();
      const isToday =
        d.getDate() === today.getDate() &&
        d.getMonth() === today.getMonth() &&
        d.getFullYear() === today.getFullYear();

      if (isToday) {
        return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
      }
      return d.toLocaleDateString('en-GB', {
        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
      });
    },

    badgeClass(status) {
      const map = {
        new:            'bg-blue-100 text-blue-700',
        auto_contacted: 'bg-yellow-100 text-yellow-700',
        replied:        'bg-green-100 text-green-700',
        booked:         'bg-purple-100 text-purple-700',
      };
      return map[status] || 'bg-gray-100 text-gray-600';
    },

    templateLabel(key) {
      const map = { sms_1: 'Initial message', sms_2: 'Follow-up 1', sms_3: 'Follow-up 2' };
      return map[key] || key;
    },
  };
}
