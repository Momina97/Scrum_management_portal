# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ScrumStoryPointConfig(models.Model):
    _name = 'project.scrum.story.point.config'
    _description = 'Scrum Story Point Configuration'

    name = fields.Char(default='Fibonacci Hour Mapping', readonly=True)

    # Explicit Min and Max fields for absolute control
    sp_1_min = fields.Float(string="1 SP (Min)", default=0.0)
    sp_1_max = fields.Float(string="1 SP (Max)", default=1.5)

    sp_2_min = fields.Float(string="2 SP (Min)", default=1.5)
    sp_2_max = fields.Float(string="2 SP (Max)", default=3.0)

    sp_3_min = fields.Float(string="3 SP (Min)", default=3.0)
    sp_3_max = fields.Float(string="3 SP (Max)", default=6.0)

    sp_5_min = fields.Float(string="5 SP (Min)", default=6.0)
    sp_5_max = fields.Float(string="5 SP (Max)", default=12.0)

    sp_8_min = fields.Float(string="8 SP (Min)", default=12.0)
    sp_8_max = fields.Float(string="8 SP (Max)", default=20.0)

    sp_13_min = fields.Float(string="13 SP (Min)", default=20.0)
    sp_13_max = fields.Float(string="13 SP (Max)", default=0.0)  # 0.0 acts as infinity

    @api.model
    def get_singleton_id(self):
        """ Used by the Owl SPA to fetch or create the single configuration record """
        record = self.search([], limit=1)
        if not record:
            record = self.create({})
        return record.id

    @api.model
    def get_sp_configuration(self):
        """
        Returns the exact MAX of the custom ranges for when a user manually selects an SP.
        """
        record_id = self.get_singleton_id()
        config = self.browse(record_id)
        return {
            '1': config.sp_1_max,
            '2': config.sp_2_max,
            '3': config.sp_3_max,
            '5': config.sp_5_max,
            '8': config.sp_8_max,
            '13': config.sp_13_max if config.sp_13_max > 0 else config.sp_13_min,
        }

    @api.model
    def compute_sp_from_hours(self, hours):
        """
        Boundary rule: MAX is inclusive, MIN is exclusive.
        First band's MIN is inclusive so values just above 0 still match SP 1.

        Symmetry guarantee: MAX of SP N computes back to SP N.
        This keeps the SP-dropdown ↔ hours-field cascade stable.
        """
        if hours <= 0:
            return '0'

        record_id = self.get_singleton_id()
        config = self.browse(record_id)

        bands = [
            ('1', config.sp_1_min, config.sp_1_max),
            ('2', config.sp_2_min, config.sp_2_max),
            ('3', config.sp_3_min, config.sp_3_max),
            ('5', config.sp_5_min, config.sp_5_max),
            ('8', config.sp_8_min, config.sp_8_max),
            ('13', config.sp_13_min, float('inf') if config.sp_13_max <= 0 else config.sp_13_max),
        ]

        for idx, (sp, b_min, b_max) in enumerate(bands):
            if idx == 0:
                if b_min <= hours <= b_max:
                    return sp
            else:
                if b_min < hours <= b_max:
                    return sp

        return '0'