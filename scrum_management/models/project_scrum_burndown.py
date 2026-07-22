from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class ProjectSprintBurndownSnapshot(models.Model):
    _name = 'project.sprint.burndown.snapshot'
    _description = 'Daily Sprint Burndown Snapshot'
    _order = 'date asc'

    sprint_id = fields.Many2one('project.scrum.sprint', string='Sprint', required=True, ondelete='cascade')
    project_id = fields.Many2one('project.project', related='sprint_id.project_id', store=True)
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)

    remaining_points = fields.Float(string='Remaining Story Points')
    total_spent_hours = fields.Float(string='Total Spent Hours')

    _sql_constraints = [
        ('unique_date_sprint', 'unique(sprint_id, date)', 'One snapshot per day per sprint!')
    ]

    @api.model
    def get_burndown_chart_data(self, project_id=None):
        """
        Fetches ALL sprint burndown data for the project in one shot.
        JS handles filtering — no re-fetching on sprint change.
        """
        if not project_id:
            return []
        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            _logger.warning("get_burndown_chart_data: invalid project_id=%s", project_id)
            return []

        try:
            sprints = self.env['project.scrum.sprint'].search([
                ('project_id', '=', pid)
            ], order='start_date asc')

            if not sprints:
                return []

            result = []
            for sprint in sprints:
                try:
                    snapshots = self.search_read(
                        [('sprint_id', '=', sprint.id), ('project_id', '=', pid)],
                        ['date', 'remaining_points', 'total_spent_hours'],
                        order='date asc'
                    )
                    for s in snapshots:
                        if hasattr(s['date'], 'isoformat'):
                            s['date'] = s['date'].isoformat()

                    result.append({
                        'sprint_id': sprint.id,
                        'sprint_name': sprint.name,
                        'sprint_state': sprint.state,
                        'start_date': str(sprint.start_date) if sprint.start_date else False,
                        'end_date': str(sprint.end_date) if sprint.end_date else False,
                        'total_points': sum(sprint.task_ids.mapped('story_points') or [0.0]),
                        'snapshots': snapshots
                    })
                except Exception as e:
                    _logger.error("Burndown: failed processing sprint %s: %s", sprint.id, e)
                    continue

            return result

        except Exception as e:
            _logger.error("get_burndown_chart_data failed for project %s: %s", project_id, e)
            return []

    def _cron_update_burndown_snapshots(self):
        """
        Cron Job: Daily burndown snapshot for all active sprints.
        Runs daily at midnight.
        """
        today = fields.Date.context_today(self)
        active_sprints = self.env['project.scrum.sprint'].search([
            ('state', '=', 'active')
        ])

        for sprint in active_sprints:
            try:
                # Remaining = non-done task story points
                remaining_tasks = sprint.task_ids.filtered(lambda t: t.state != '1_done')
                rem_pts = sum(remaining_tasks.mapped('story_points') or [0.0])
                spent_hrs = sum(sprint.task_ids.mapped('effective_hours') or [0.0])

                existing = self.search([
                    ('sprint_id', '=', sprint.id),
                    ('date', '=', today)
                ], limit=1)

                vals = {
                    'sprint_id': sprint.id,
                    'date': today,
                    'remaining_points': rem_pts,
                    'total_spent_hours': spent_hrs,
                }

                if existing:
                    existing.write(vals)
                else:
                    self.create(vals)

            except Exception as e:
                _logger.error(
                    "Burndown cron failed for sprint %s (id=%s): %s",
                    sprint.name, sprint.id, e
                )
                continue