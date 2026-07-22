from odoo import models, fields, api, _


class ScrumProjectDashboard(models.TransientModel):
    _name = 'scrum.project.dashboard'
    _description = 'Per-Project Scrum Dashboard'

    name = fields.Char(string="Dashboard Name")
    project_id = fields.Many2one('project.project', string="Project", required=True)

    # --- HEADER STATS ---
    sprint_count = fields.Integer(string="Total Sprints")
    active_task_count = fields.Integer(string="Active Tasks")
    backlog_count = fields.Integer(string="Backlog Items")
    completion_rate = fields.Integer(string="Completion Rate (%)")

    # --- VELOCITY & METRICS ---
    average_velocity = fields.Float(string="Avg Velocity", digits=(16, 1))
    current_velocity = fields.Integer(string="Current Sprint SP")
    total_story_points = fields.Integer(string="Total SP Scope")

    # --- RELATIONS FOR LISTS ---
    active_sprint_ids = fields.Many2many('project.scrum.sprint', string="Active Sprints")
    member_ids = fields.Many2many('res.users', string="Team Members")

    def action_open_project_settings(self):
        """ This method redirects the Client Action to the Project Settings Form View """
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'scrum_management.scrum_client_action',
            'params': {
                'project_id': self.project_id.id,
                'view_type': 'settings'
            }
        }

    @api.model
    def compute_dashboard_data(self, project_id):
        project = self.env['project.project'].browse(project_id)
        if not project.exists():
            return False

        # 1. Fetch Sprints (Standard ORM access is fine for One2many)
        sprints = project.sprint_ids
        active_sprints = sprints.filtered(lambda s: s.state == 'active')
        completed_sprints = sprints.filtered(lambda s: s.state == 'completed')

        # 2. ACCURATE TASK COUNTS (Direct DB Search)
        # Using search_count guarantees we get the real database state, bypassing any cache/compute issues.
        Task = self.env['project.task']

        # All tasks in this project
        total_tasks = Task.search_count([('project_id', '=', project.id)])

        # Completed tasks (Closed/Done)
        completed_tasks_count = Task.search_count([
            ('project_id', '=', project.id),
            ('is_closed', '=', True)
        ])

        # Active (In Progress) tasks - Assigned to a Sprint
        active_task_count = Task.search_count([
            ('project_id', '=', project.id),
            ('sprint_id', '!=', False),
            ('is_closed', '=', False)
        ])

        # Backlog tasks - No sprint assigned
        backlog_count = Task.search_count([
            ('project_id', '=', project.id),
            ('sprint_id', '=', False),
            ('is_closed', '=', False)
        ])

        # Total Story Points (Scope)
        # We need a search() here to sum the points
        all_tasks = Task.search([('project_id', '=', project.id)])
        total_scope_sp = sum(all_tasks.mapped('story_points'))

        # 3. Calculate Velocity
        avg_velocity = 0.0
        if completed_sprints:
            avg_velocity = sum(completed_sprints.mapped('velocity')) / len(completed_sprints)

        current_sp = sum(active_sprints.mapped('total_story_points'))

        # 4. Calculate Completion Rate
        comp_rate = 0
        if total_tasks > 0:
            comp_rate = round((completed_tasks_count / total_tasks) * 100)

        # 5. Create/Update Transient Record
        dashboard = self.create({
            'name': f"Dashboard: {project.name}",
            'project_id': project.id,
            'sprint_count': len(sprints),
            'active_task_count': active_task_count,
            'backlog_count': backlog_count,
            'completion_rate': int(comp_rate),
            'average_velocity': avg_velocity,
            'current_velocity': current_sp,
            'total_story_points': total_scope_sp,
            'active_sprint_ids': [(6, 0, active_sprints.ids)],
            'member_ids': [(6, 0, project.team_member_ids.ids)],
        })

        return dashboard.id