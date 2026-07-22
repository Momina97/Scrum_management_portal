from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class ProjectVelocitySnapshot(models.Model):
    _name = 'project.velocity.snapshot'
    _description = 'Sprint Velocity Historical Snapshot'
    _order = 'date desc'

    project_id = fields.Many2one('project.project', string="Project", required=True, ondelete='cascade')
    sprint_id = fields.Many2one('project.scrum.sprint', string="Sprint", required=True, ondelete='cascade')
    date = fields.Date(string="Snapshot Date", default=fields.Date.context_today)

    planned_velocity = fields.Float(string="Planned Points", help="Points committed at sprint start.")
    delivered_velocity = fields.Float(string="Delivered Points", help="Points completed at sprint end.")
    rolling_avg = fields.Float(string="3-Sprint Rolling Average")

    @api.model
    def get_velocity_chart_data(self, project_id):
        """
        API endpoint: Returns raw snapshot data for the velocity chart.
        """
        if not project_id:
            return []
        try:
            snapshots = self.search_read(
                [('project_id', '=', project_id)],
                ['date', 'sprint_id', 'planned_velocity', 'delivered_velocity', 'rolling_avg'],
                order='sprint_id desc',
                limit=50
            )
            return snapshots
        except Exception as e:
            _logger.error("get_velocity_chart_data failed for project %s: %s", project_id, e)
            return []

    def _cron_calculate_end_date_velocity(self):
        """
        Cron Job: Takes a velocity snapshot of sprints ending today.
        Runs daily at 11:59 PM.
        """
        today = fields.Date.context_today(self)
        sprints = self.env['project.scrum.sprint'].search([
            ('end_date', '=', today),
            ('project_id', '!=', False)
        ])

        for sprint in sprints:
            try:
                # 1. Planned = all task story points
                planned = sum(sprint.task_ids.mapped('story_points') or [0.0])

                # 2. Delivered = closed task story points
                closed_tasks = sprint.task_ids.filtered(lambda t: t.state == '1_done')
                delivered = sum(closed_tasks.mapped('story_points') or [0.0])

                # 3. Rolling Average — last 2 snapshots before this sprint
                prev_snapshots = self.search([
                    ('project_id', '=', sprint.project_id.id),
                    ('sprint_id', '!=', sprint.id)
                ], order='date desc', limit=2)

                total_delivered = delivered + sum(prev_snapshots.mapped('delivered_velocity') or [0.0])
                count = 1 + len(prev_snapshots)
                rolling_avg = total_delivered / count if count > 0 else 0.0

                # 4. Upsert snapshot
                existing = self.search([('sprint_id', '=', sprint.id)], limit=1)

                vals = {
                    'project_id': sprint.project_id.id,
                    'sprint_id': sprint.id,
                    'planned_velocity': planned,
                    'delivered_velocity': delivered,
                    'rolling_avg': rolling_avg,
                    'date': today,
                }

                if existing:
                    existing.write(vals)
                else:
                    self.create(vals)

                # 5. Update project rolling velocity
                sprint.project_id.rolling_velocity = rolling_avg

            except Exception as e:
                _logger.error(
                    "Velocity cron failed for sprint %s (id=%s): %s",
                    sprint.name, sprint.id, e
                )
                continue