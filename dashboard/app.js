// SUPABASE_URL, SUPABASE_ANON_KEY, and FUNCTION_BASE are defined in index.html

function crmApp() {
  return {
    // ── Auth ──────────────────────────────────────────────────────────────
    loggedIn: false,
    loginEmail: '',
    loginPassword: '',
    loginError: '',
    loginLoading: false,
    _supabase: null,

    // ── CRM state ─────────────────────────────────────────────────────────
    leads: [],
    selectedLead: null,
    messages: [],
    replyText: '',
    filterStatus: 'all',
    sending: false,
    realtimeConnected: false,
    showLost: false,
    config: { template_2: '', template_3: '' },
    _channel: null,

    // Template editor
    showTemplates: false,
    templates: [],
    savingTemplate: null,

    // Ads
    showAds: false,
    adsLoading: false,
    adsDateRange: 'last_7d',
    adsData: null,
    adsError: null,

    statuses: [
      { value: 'all',         label: 'All' },
      { value: 'new',         label: 'New' },
      { value: 'contacted',   label: 'Contacted' },
      { value: 'interested',  label: 'Interested' },
      { value: 'call_booked', label: 'Call Booked' },
      { value: 'enrolled',    label: 'Enrolled' },
      { value: 'lost',        label: 'Lost' },
    ],

    // ── Init ──────────────────────────────────────────────────────────────

    async init() {
      this._supabase = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

      const { data: { session } } = await this._supabase.auth.getSession();
      if (session) {
        this.loggedIn = true;
        await this._loadApp();
      }

      document.addEventListener('visibilitychange', async () => {
        if (!document.hidden && this.loggedIn) {
          this.connectRealtime();
          this.loadLeads();
          if (this.selectedLead) {
            await this.loadMessages(this.selectedLead.id);
            this.$nextTick(() => this.scrollToBottom());
          }
        }
      });

      this._supabase.auth.onAuthStateChange(async (event, session) => {
        if (event === 'SIGNED_IN' && session) {
          this.loggedIn = true;
          await this._loadApp();
        } else if (event === 'SIGNED_OUT') {
          this.loggedIn = false;
          this.leads = [];
          this.selectedLead = null;
          this.messages = [];
          if (this._channel) { this._channel.unsubscribe(); this._channel = null; }
        }
      });
    },

    async _loadApp() {
      await Promise.all([this.loadConfig(), this.loadLeads()]);
      this.connectRealtime();
      // Auto-reconnect if realtime drops
      setInterval(() => {
        if (!this.realtimeConnected && this.loggedIn) this.connectRealtime();
      }, 30000);
    },

    // ── Auth actions ──────────────────────────────────────────────────────

    async login() {
      if (!this.loginEmail || !this.loginPassword) return;
      this.loginLoading = true;
      this.loginError = '';
      const { error } = await this._supabase.auth.signInWithPassword({
        email: this.loginEmail,
        password: this.loginPassword,
      });
      this.loginLoading = false;
      if (error) this.loginError = error.message;
    },

    async logout() {
      await this._supabase.auth.signOut();
    },

    async _token() {
      const { data: { session } } = await this._supabase.auth.getSession();
      return session?.access_token ?? '';
    },

    async _fetch(url, options = {}) {
      const token = await this._token();
      return fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
          ...(options.headers ?? {}),
        },
      });
    },

    // ── Data loading ──────────────────────────────────────────────────────

    async loadConfig() {
      try {
        const res = await this._fetch(`${FUNCTION_BASE}/crm-api/config`);
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
        const res = await this._fetch(url);
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

    // Leads shown in the sidebar — hides lost by default when filter is 'all'
    visibleLeads() {
      if (this.filterStatus !== 'all' || this.showLost) return this.leads;
      return this.leads.filter(l => l.status !== 'lost');
    },

    hiddenLostCount() {
      if (this.filterStatus !== 'all' || this.showLost) return 0;
      return this.leads.filter(l => l.status === 'lost').length;
    },

    async selectLead(lead) {
      this.selectedLead = lead;
      this.messages = [];
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

    // Merge new messages into the array by ID — prevents realtime/HTTP race condition
    _upsertMessages(newMsgs) {
      for (const msg of newMsgs) {
        const idx = this.messages.findIndex(m => m.id === msg.id);
        if (idx === -1) {
          const pos = this.messages.findIndex(m => new Date(m.sent_at) > new Date(msg.sent_at));
          if (pos === -1) this.messages.push(msg);
          else this.messages.splice(pos, 0, msg);
        } else {
          this.messages[idx] = msg;
        }
      }
    },

    async loadMessages(leadId) {
      try {
        const res = await this._fetch(`${FUNCTION_BASE}/crm-api/leads/${leadId}/messages`);
        if (!res.ok) return;
        const msgs = await res.json();
        if (this.selectedLead?.id !== leadId) return;
        // Upsert rather than replace — preserves optimistic/realtime messages
        this._upsertMessages(msgs);
        this.$nextTick(() => this.scrollToBottom());
      } catch (e) {
        console.error('Failed to load messages:', e);
      }
    },

    // ── Actions ───────────────────────────────────────────────────────────

    async sendReply() {
      if (!this.replyText.trim() || this.sending || !this.selectedLead) return;
      this.sending = true;
      const body = this.replyText;
      const tempId = 'temp-' + Date.now();
      // Push optimistically — shown immediately, no refresh needed
      this.messages.push({ id: tempId, direction: 'outbound', body, sent_at: new Date().toISOString(), lead_id: this.selectedLead.id });
      this.replyText = '';
      this.$nextTick(() => this.scrollToBottom());
      try {
        const res = await this._fetch(`${FUNCTION_BASE}/crm-api/leads/${this.selectedLead.id}/send`, {
          method: 'POST',
          body: JSON.stringify({ body }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          this.messages = this.messages.filter(m => m.id !== tempId);
          this.replyText = body;
          alert('Send failed: ' + (err.error || res.statusText));
        } else {
          const { message } = await res.json();
          if (message) {
            // Replace temp with confirmed server record
            const idx = this.messages.findIndex(m => m.id === tempId);
            if (idx !== -1) this.messages[idx] = message;
            else this._upsertMessages([message]);
          }
        }
      } catch (e) {
        console.error('Send error:', e);
        this.messages = this.messages.filter(m => m.id !== tempId);
        this.replyText = body;
      } finally {
        this.sending = false;
      }
    },

    async sendTemplate(n) {
      if (this.sending || !this.selectedLead) return;
      this.sending = true;
      try {
        const res = await this._fetch(`${FUNCTION_BASE}/crm-api/leads/${this.selectedLead.id}/template/${n}`, {
          method: 'POST',
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert('Template send failed: ' + (err.error || res.statusText));
        } else {
          const { message } = await res.json();
          if (message) {
            this._upsertMessages([message]);
            this.$nextTick(() => this.scrollToBottom());
          }
        }
      } catch (e) {
        console.error('Template send error:', e);
      } finally {
        this.sending = false;
      }
    },

    async toggleFlag(leadId, flagged) {
      try {
        await this._fetch(`${FUNCTION_BASE}/crm-api/leads/${leadId}/flag`, {
          method: 'PATCH',
          body: JSON.stringify({ flagged }),
        });
        await this.loadLeads();
      } catch (e) {
        console.error('Flag error:', e);
      }
    },

    async dismissReply(leadId) {
      try {
        await this._fetch(`${FUNCTION_BASE}/crm-api/leads/${leadId}/dismiss-reply`, { method: 'PATCH' });
        await this.loadLeads();
      } catch (e) {
        console.error('Dismiss reply error:', e);
      }
    },

    async updateStatus(leadId, newStatus) {
      try {
        await this._fetch(`${FUNCTION_BASE}/crm-api/leads/${leadId}/status`, {
          method: 'PATCH',
          body: JSON.stringify({ status: newStatus }),
        });
        await this.loadLeads();
      } catch (e) {
        console.error('Status update failed:', e);
      }
    },

    async deleteLead(leadId) {
      if (!confirm('Delete this lead and all their messages? This cannot be undone.')) return;
      try {
        const res = await this._fetch(`${FUNCTION_BASE}/crm-api/leads/${leadId}`, { method: 'DELETE' });
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

    async openAds() {
      this.showAds = true;
      this.showTemplates = false;
      this.selectedLead = null;
      await this.loadAdsData();
    },

    async loadAdsData() {
      this.adsLoading = true;
      this.adsError = null;
      try {
        const res = await this._fetch(`${FUNCTION_BASE}/meta-ads-api?date_preset=${this.adsDateRange}`);
        const data = await res.json();
        if (!res.ok) {
          this.adsError = data.error || 'Failed to load ad data';
        } else {
          this.adsData = data;
        }
      } catch (e) {
        console.error('Failed to load ads:', e);
        this.adsError = 'Failed to load ad data';
      } finally {
        this.adsLoading = false;
      }
    },

    async openTemplates() {
      this.showTemplates = true;
      this.showAds = false;
      this.selectedLead = null;
      try {
        const res = await this._fetch(`${FUNCTION_BASE}/crm-api/templates`);
        if (res.ok) this.templates = await res.json();
      } catch (e) {
        console.error('Failed to load templates:', e);
      }
    },

    async saveTemplate(tmpl) {
      this.savingTemplate = tmpl.key;
      try {
        const res = await this._fetch(`${FUNCTION_BASE}/crm-api/templates/${tmpl.key}`, {
          method: 'PATCH',
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

    // ── Realtime ──────────────────────────────────────────────────────────

    async connectRealtime() {
      if (this._channel) this._channel.unsubscribe();

      const { data: { session } } = await this._supabase.auth.getSession();
      if (session?.access_token) {
        this._supabase.realtime.setAuth(session.access_token);
      }

      this._channel = this._supabase
        .channel('crm-changes')
        .on('postgres_changes', { event: '*', schema: 'public', table: 'leads' }, () => {
          this.loadLeads();
        })
        .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'messages' }, (payload) => {
          const msg = payload.new;
          if (this.selectedLead && msg.lead_id === this.selectedLead.id) {
            this._upsertMessages([msg]);
            this.$nextTick(() => this.scrollToBottom());
          }
          this.loadLeads();
        })
        .subscribe((status) => {
          this.realtimeConnected = status === 'SUBSCRIBED';
        });
    },

    // ── Helpers ───────────────────────────────────────────────────────────

    scrollToBottom() {
      const el = document.getElementById('chat-messages');
      if (el) el.scrollTop = el.scrollHeight;
    },

    hasReplyBadge(lead) {
      return lead.last_message_direction === 'inbound' &&
        (!lead.reply_dismissed_at || new Date(lead.last_message_at) > new Date(lead.reply_dismissed_at));
    },

    formatAge(iso) {
      if (!iso) return '';
      const diff = Date.now() - new Date(iso).getTime();
      const mins = Math.floor(diff / 60000);
      if (mins < 1) return 'Just now';
      if (mins < 60) return `${mins}m ago`;
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return `${hrs}h ago`;
      const days = Math.floor(hrs / 24);
      return `${days}d ago`;
    },

    formatTime(iso) {
      const d = new Date(iso);
      const today = new Date();
      const isToday = d.getDate() === today.getDate() &&
        d.getMonth() === today.getMonth() &&
        d.getFullYear() === today.getFullYear();
      if (isToday) return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
      return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    },

    badgeClass(status) {
      const map = {
        new:         'bg-gray-100 text-gray-600',
        contacted:   'bg-blue-100 text-blue-700',
        interested:  'bg-yellow-100 text-yellow-700',
        call_booked: 'bg-purple-100 text-purple-700',
        enrolled:    'bg-green-100 text-green-700',
        lost:        'bg-red-100 text-red-500',
      };
      return map[status] || 'bg-gray-100 text-gray-600';
    },

    templateLabel(key) {
      const map = { sms_1: 'Initial message', sms_2: 'Follow-up 1', sms_3: 'Follow-up 2' };
      return map[key] || key;
    },
  };
}
