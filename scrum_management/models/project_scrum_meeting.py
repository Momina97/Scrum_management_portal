from odoo import models, fields, api, _
from datetime import timedelta

class ScrumMeeting(models.Model):
    _name = 'project.scrum.meeting'
    _description = 'Scrum Meeting'
    # Inherit from mail.thread to get chatter functionality
    _inherit = ['mail.thread']

    subject = fields.Char(string='Subject', required=True, tracking=True )
    date = fields.Datetime(string='Date', default=fields.Datetime.now, tracking=True)
    project_id = fields.Many2one('project.project', string='Project', ondelete='cascade')
    sprint_id = fields.Many2one('project.scrum.sprint', string='Sprint')
    attendee_ids = fields.Many2many('res.users', string="Attendees", tracking=True)

    # --- NEW & MODIFIED FIELDS ---
    # 1. Modified state field to include 'cancelled'
    state = fields.Selection([
        ('draft', 'Draft'),
        ('held', 'Held'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)

    # 2. New HTML field for a rich-text description/agenda
    description = fields.Html(string='Agenda / Description')

    # --- OVERRIDDEN CREATE METHOD ---
    @api.model_create_multi
    def create(self, vals_list):
        """ Override create to automatically send an invitation email. """
        meetings = super(ScrumMeeting, self).create(vals_list)
        for meeting in meetings:
            # Send the invitation email using the new template
            meeting._send_meeting_mail('scrum_management.email_template_meeting_invitation')
        return meetings

    # --- ACTION METHODS FOR BUTTONS ---
    def action_mark_as_held(self):
        """ Sets the meeting state to 'Held'. """
        self.write({'state': 'held'})

    def action_cancel_meeting(self):
        """ Sets the meeting state to 'Cancelled' and sends a notification. """
        self.write({'state': 'cancelled'})
        for meeting in self:
            meeting._send_meeting_mail('scrum_management.email_template_meeting_cancellation')

    # --- AUTOMATED ACTION METHOD FOR CRON JOB ---
    @api.model
    def _send_meeting_reminders(self):
        """
        This method is designed to be called by a scheduled action (cron job).
        It finds all upcoming meetings within the next 24 hours and sends a reminder.
        """
        # Calculate the time window: now -> 24 hours from now
        now = fields.Datetime.now()
        in_24_hours = now + timedelta(days=1)

        # Find meetings in the window that are still in the 'Draft' state
        upcoming_meetings = self.search([
            ('state', '=', 'draft'),
            ('date', '>=', now),
            ('date', '<=', in_24_hours)
        ])

        for meeting in upcoming_meetings:
            meeting._send_meeting_mail('scrum_management.email_template_meeting_reminder')

    # --- HELPER METHOD FOR SENDING EMAILS ---
    def _send_meeting_mail(self, template_xml_id):
        """
        Helper method to send an email to all attendees for a specific meeting
        using a specified email template.
        """
        self.ensure_one()
        if not self.attendee_ids:
            return # Don't try to send an email if there are no attendees

        template = self.env.ref(template_xml_id)
        template.send_mail(self.id, force_send=True)