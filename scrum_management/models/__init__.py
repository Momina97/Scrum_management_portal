# models/__init__.py
# -*- coding: utf-8 -*-

# Import custom models first
from . import scrum_dashboard
from . import scrum_project_dashboard
from . import project_scrum_sprint
from . import project_scrum_release
from . import project_scrum_meeting
from. import project_velocity_snapshot
from . import project_scrum_burndown

#Then import the models that inherit from Odoo's core
from . import project_project
from . import project_scrum_task
from . import project_task_type
from . import project_scrum_sp_config
