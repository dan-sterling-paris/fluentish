function crmApp() {
  return {
    leads: [],
    selectedLead: null,
    messages: [],
    replyText: '',
    filterStatus: 'all',
    sending: false,
    sseConnected: false,
    _eventSource: null,

    statuses: [
      { value: 'all',            label: 'All' },
      { value: 'new',            label: 'New' },
      { value: 'auto_contacted', label: 'Auto-contacted' },
      { value: 'replied',        label: 'Replied' },
      { value: 'booked',         label: 'Booked' },
    ],

    async init() {
      await this.loadLeads();
      this.connectSSE();
    },

    async loadLeads() {
      const url = this.filterStatus === 'all'
        ? '/api/leads'
        : `/api/leads?status=${this.filterStatus}`;
      try {
        const res = await fetch(url);
        if (!res.ok) return;
        const fresh = await res.json();
        // If the selected lead is in the new list, update its data in-place
        if (this.selectedLead) {
          const updated = fresh.find(l => l.id === this.selectedLead.id);
          if (updated) this.selectedLead = updated;
        }
        this.leads = fresh;
      } catch (err) {
        console.error('Failed to load leads:', err);
      }
    },

    async selectLead(lead) {
      this.selectedLead = lead;
      this.messages = [];
      this.replyText = '';
      await this.loadMessages(lead.id);
      this.$nextTick(() => this.scrollToBottom());
    },

    async loadMessages(leadId) {
      try {
        const res = await fetch(`/api/leads/${leadId}/messages`);
        if (!res.ok) return;
        const msgs = await res.json();
        if (this.selectedLead?.id !== leadId) return;
        this.messages = msgs;
      } catch (err) {
        console.error('Failed to load messages:', err);
      }
    },

    async sendReply() {
      if (!this.replyText.trim() || this.sending || !this.selectedLead) return;
      this.sending = true;
      const body = this.replyText;
      const leadId = this.selectedLead.id;
      this.replyText = '';
      try {
        const res = await fetch(`/api/leads/${leadId}/send`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ body }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert('Send failed: ' + (err.detail || res.statusText));
          this.replyText = body; // restore on failure
        } else {
          await this.loadMessages(leadId);
          this.$nextTick(() => this.scrollToBottom());
        }
      } catch (err) {
        console.error('Send error:', err);
        this.replyText = body;
      } finally {
        this.sending = false;
      }
    },

    async sendTemplate(n) {
      if (this.sending || !this.selectedLead) return;
      this.sending = true;
      const leadId = this.selectedLead.id;
      try {
        const res = await fetch(`/api/leads/${leadId}/template/${n}`, {
          method: 'POST',
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert('Template send failed: ' + (err.detail || res.statusText));
        } else {
          await this.loadMessages(leadId);
          this.$nextTick(() => this.scrollToBottom());
        }
      } catch (err) {
        console.error('Template send error:', err);
      } finally {
        this.sending = false;
      }
    },

    async updateStatus(leadId, newStatus) {
      // Optimistic: UI already updated via x-model. Persist via dedicated endpoint
      // (we POST a custom message body of '' which will fail; instead call send_template
      // or do nothing — status is auto-managed by the server).
      // For manual "Booked" overrides we post directly to the leads status endpoint.
      try {
        await fetch(`/api/leads/${leadId}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus }),
        });
        // Reload so sidebar reflects new status
        await this.loadLeads();
      } catch (err) {
        console.error('Status update failed:', err);
      }
    },

    connectSSE() {
      if (this._eventSource) {
        this._eventSource.close();
      }
      this._eventSource = new EventSource('/events');

      this._eventSource.onopen = () => {
        this.sseConnected = true;
      };

      this._eventSource.onmessage = async (event) => {
        let data;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }
        this.sseConnected = true;

        if (data.type === 'new_message') {
          // Always refresh lead list (status badges + ordering)
          await this.loadLeads();

          // If this message belongs to the active conversation, append it
          if (this.selectedLead && data.lead_id === this.selectedLead.id) {
            const alreadyHave = this.messages.some(m => m.id === data.id);
            if (!alreadyHave) {
              this.messages.push({
                id: data.id,
                lead_id: data.lead_id,
                direction: data.direction,
                body: data.body,
                sent_at: data.sent_at,
              });
              this.$nextTick(() => this.scrollToBottom());
            }
          }
        }

        if (data.type === 'status_update') {
          await this.loadLeads();
        }
      };

      this._eventSource.onerror = () => {
        this.sseConnected = false;
        // Browser auto-reconnects EventSource — no manual retry needed
      };
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
  };
}
