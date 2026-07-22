from odoo import models, fields, api, _
from datetime import timedelta
import json
import logging

_logger = logging.getLogger(__name__)


class ScrumDashboard(models.Model):
    _name = 'scrum.dashboard'
    _description = 'Scrum Dashboard Data'

    name = fields.Char(string="Last Updated", readonly=True)
    active_sprint_count = fields.Integer(string="Active Sprints", readonly=True)
    tasks_in_sprints = fields.Integer(string="Tasks in Sprints", readonly=True)
    total_sp_in_sprints = fields.Integer(string="Total SP in Sprints", readonly=True)
    burn_rate_per_day = fields.Float(string="Sprint Burn Rate (SP/Day)", readonly=True, digits=(16, 1))
    backlog_task_count = fields.Integer(string="Backlog Tasks", readonly=True)
    backlog_sp_count = fields.Integer(string="Backlog Story Points", readonly=True)
    completed_tasks_month = fields.Integer(string="Tasks Completed This Month", readonly=True)
    completed_sp_month = fields.Integer(string="SP Completed This Month", readonly=True)

    active_sprint_ids = fields.Many2many('project.scrum.sprint', 'dashboard_active_sprints_rel', readonly=True)

    project_breakdown_ids = fields.One2many('scrum.dashboard.line', 'dashboard_id', readonly=True)
    top_performer_ids = fields.One2many('scrum.dashboard.line', 'dashboard_id_perf', readonly=True)

    upcoming_meeting_ids = fields.Many2many('project.scrum.meeting', 'dashboard_meetings_rel', readonly=True)
    burndown_sprint_id = fields.Many2one('project.scrum.sprint', string="Burndown Chart Sprint", readonly=True)
    burndown_chart_json = fields.Text(string="Burndown Chart JSON", readonly=True)

    total_project_count = fields.Integer(string="Total Software Projects", readonly=True)
    project_status_ids = fields.One2many('scrum.dashboard.status.line', 'dashboard_id', readonly=True)
    team_allocation_ids = fields.One2many('scrum.dashboard.team.line', 'dashboard_id', readonly=True)


    def action_refresh_dashboard(self):
        self.ensure_one()

        # 0. SEPARATION: Identify all Scrum Projects
        scrum_p_ids = self.env['project.project'].search([('project_type', '=', 'scrum')]).ids

        if not scrum_p_ids:
            # Reset dashboard if no scrum projects exist
            self.write({
                'active_sprint_count': 0,
                'tasks_in_sprints': 0,
                'total_sp_in_sprints': 0,
                'burn_rate_per_day': 0,
                'backlog_task_count': 0,
                'backlog_sp_count': 0,
                'completed_tasks_month': 0,
                'completed_sp_month': 0,
                'active_sprint_ids': [(5, 0, 0)],
                'project_breakdown_ids': [(5, 0, 0)],
                'top_performer_ids': [(5, 0, 0)],
                'upcoming_meeting_ids': [(5, 0, 0)],
                'total_project_count': 0,
                'project_status_ids': [(5, 0, 0)],
                'team_allocation_ids': [(5, 0, 0)],
                'burndown_chart_json': "{}",
                'name': f"Last Updated: {fields.Datetime.now()} (No Scrum Projects Found)"
            })
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        # 1. Active Work Metrics (Restricted to Scrum Projects)
        active_sprints = self.env['project.scrum.sprint'].search([
            ('project_id', 'in', scrum_p_ids),
            ('state', '=', 'active')
        ])
        tasks_in_sprints = self.env['project.task'].search_count([
            ('project_id', 'in', scrum_p_ids),
            ('sprint_id', 'in', active_sprints.ids)
        ])
        total_sp_in_sprints = sum(active_sprints.mapped('total_story_points'))
        completed_sp_in_sprints = sum(active_sprints.mapped('completed_story_points'))

        total_days_elapsed = sum((fields.Date.today() - s.start_date).days + 1 for s in active_sprints if
                                 s.start_date and s.start_date <= fields.Date.today())
        true_burn_rate = (completed_sp_in_sprints / total_days_elapsed) if total_days_elapsed > 0 else 0.0

        # 2. Backlog Metrics
        backlog_tasks = self.env['project.task'].search([
            ('project_id', 'in', scrum_p_ids),
            ('sprint_id', '=', False)
        ])
        backlog_task_count = len(backlog_tasks)
        backlog_sp_count = sum(backlog_tasks.mapped('story_points'))

        start_of_month = fields.Date.today().replace(day=1)
        completed_tasks_month_recs = self.env['project.task'].search([
            ('project_id', 'in', scrum_p_ids),
            ('is_closed', '=', True),
            ('write_date', '>=', start_of_month)
        ])

        # 3. Project Breakdown
        project_data = self.env['project.task'].read_group(
            [('project_id', 'in', scrum_p_ids)], ['project_id'], ['project_id'])
        line_commands = [(5, 0, 0)]
        if project_data:
            max_value = max((d['project_id_count'] for d in project_data), default=0)
            for data in project_data:
                percentage = (data['project_id_count'] / max_value * 100) if max_value > 0 else 0
                line_commands.append((0, 0, {
                    'name': data['project_id'][1],
                    'value': data['project_id_count'],
                    'percentage': percentage
                }))

        # 4. Top Performers (Calculated from Scrum Tasks only)
        user_points_map = {}
        for task in completed_tasks_month_recs:
            if task.user_ids and task.story_points > 0:
                points = task.story_points
                for user in task.user_ids:
                    if user.id not in user_points_map:
                        user_points_map[user.id] = {'name': user.name, 'sp': 0}
                    user_points_map[user.id]['sp'] += points

        sorted_users = sorted(user_points_map.items(), key=lambda item: item[1]['sp'], reverse=True)[:5]
        perf_commands = [(5, 0, 0)]
        for uid, data in sorted_users:
            perf_commands.append((0, 0, {
                'user_id': uid,
                'name': data['name'],
                'value': data['sp'],
                'is_performer': True
            }))

        # 5. Burndown JSON (Most recent active Scrum Sprint)
        burndown_sprint = self.env['project.scrum.sprint'].search(
            [('project_id', 'in', scrum_p_ids), ('state', '=', 'active'), ('start_date', '!=', False)],
            order='start_date desc', limit=1
        )
        burndown_chart_data = {}
        if burndown_sprint:
            start_date = burndown_sprint.start_date
            end_date = burndown_sprint.end_date
            sprint_tasks = burndown_sprint.task_ids
            total_sp = sum(sprint_tasks.mapped('story_points'))

            # --- FIX: Ensure both dates are set before comparing ---
            if total_sp > 0 and start_date and end_date and start_date < end_date:
                completed_tasks = sprint_tasks.filtered(lambda t: t.is_closed and t.write_date)
                day_count = (end_date - start_date).days + 1
                sp_per_day = total_sp / (day_count - 1) if day_count > 1 else total_sp
                labels, ideal_data, actual_data = [], [], []
                for i in range(day_count):
                    current_date = start_date + timedelta(days=i)
                    labels.append(current_date.strftime('%b %d'))
                    ideal_value = round(total_sp - (i * sp_per_day), 1)
                    ideal_data.append(ideal_value if ideal_value >= 0 else 0)
                    if current_date <= fields.Date.today():
                        sp_completed_by_date = sum(
                            t.story_points for t in completed_tasks if t.write_date.date() <= current_date)
                        remaining_sp = total_sp - sp_completed_by_date
                        actual_data.append(remaining_sp)

                burndown_chart_data = {
                    'type': 'line',
                    'data': {
                        'labels': labels,
                        'datasets': [
                            {'label': 'Actual', 'data': actual_data, 'borderColor': '#8b5cf6',
                             'backgroundColor': 'rgba(139, 92, 246, 0.1)', 'tension': 0.3},
                            {'label': 'Ideal', 'data': ideal_data, 'borderColor': '#94a3b8', 'borderDash': [5, 5]}
                        ]
                    }
                }
        final_json = json.dumps(burndown_chart_data) if burndown_chart_data else "{}"

        # 6. Overview & Meetings
        today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0)
        upcoming_meetings = self.env['project.scrum.meeting'].search(
            [('project_id', 'in', scrum_p_ids), ('date', '>=', today_start)],
            order='date asc', limit=5
        )

        status_commands = [(5, 0, 0)]
        status_groups = self.env['project.project'].read_group(
            [('id', 'in', scrum_p_ids)], ['status'], ['status']
        )
        for group in status_groups:
            raw_status = group['status']
            status_label = str(raw_status).title().replace('_', ' ') if raw_status else 'Undefined'
            status_commands.append((0, 0, {
                'status_label': status_label,
                'count': group['status_count']
            }))

        team_commands = [(5, 0, 0)]
        for sprint in active_sprints:
            members = sprint.task_ids.mapped('user_ids')
            if members:
                team_commands.append((0, 0, {
                    'project_id': sprint.project_id.id,
                    'sprint_id': sprint.id,
                    'member_ids': [(6, 0, members.ids)],
                    'member_count': len(members)
                }))

        self.write({
            'active_sprint_count': len(active_sprints),
            'tasks_in_sprints': tasks_in_sprints,
            'total_sp_in_sprints': total_sp_in_sprints,
            'burn_rate_per_day': true_burn_rate,
            'backlog_task_count': backlog_task_count,
            'backlog_sp_count': backlog_sp_count,
            'completed_tasks_month': len(completed_tasks_month_recs),
            'completed_sp_month': sum(completed_tasks_month_recs.mapped('story_points')),
            'active_sprint_ids': [(6, 0, active_sprints.ids)],
            'upcoming_meeting_ids': [(6, 0, upcoming_meetings.ids)],
            'project_breakdown_ids': line_commands,
            'top_performer_ids': perf_commands,
            'name': f"Last Updated: {fields.Datetime.now()}",
            'burndown_sprint_id': burndown_sprint.id if burndown_sprint else False,
            'burndown_chart_json': final_json,
            'total_project_count': len(scrum_p_ids),
            'project_status_ids': status_commands,
            'team_allocation_ids': team_commands,
        })
        return {'type': 'ir.actions.client', 'tag': 'reload'}


class ScrumDashboardLine(models.Model):
    _name = 'scrum.dashboard.line'
    _description = 'Scrum Dashboard Data Line'
    _order = 'value desc'

    dashboard_id = fields.Many2one('scrum.dashboard')
    dashboard_id_perf = fields.Many2one('scrum.dashboard')
    is_performer = fields.Boolean()
    user_id = fields.Many2one('res.users', string="User")
    name = fields.Char(string="Label")
    value = fields.Integer(string="Value")
    percentage = fields.Integer(string="Percentage")


class ScrumDashboardStatusLine(models.Model):
    _name = 'scrum.dashboard.status.line'
    _description = 'Project Status Breakdown Line'
    _order = 'count desc'

    dashboard_id = fields.Many2one('scrum.dashboard', readonly=True)
    status_label = fields.Char(string="Status")
    count = fields.Integer(string="Count")


class ScrumDashboardTeamLine(models.Model):
    _name = 'scrum.dashboard.team.line'
    _description = 'Active Sprint Team Line'
    _order = 'project_id, sprint_id'

    dashboard_id = fields.Many2one('scrum.dashboard', readonly=True)
    project_id = fields.Many2one('project.project', string="Project", readonly=True)
    sprint_id = fields.Many2one('project.scrum.sprint', string="Active Sprint", readonly=True)
    member_ids = fields.Many2many('res.users', string="Team Members", readonly=True)
    member_count = fields.Integer(string="Members", readonly=True)