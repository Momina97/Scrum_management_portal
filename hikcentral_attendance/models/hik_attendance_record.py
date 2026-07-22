from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import pytz
from datetime import datetime, timedelta
from dateutil.parser import parse

_logger = logging.getLogger(__name__)

class HikAttendanceRecord(models.Model):
    _name = 'hik.attendance.record'
    _description = 'HikCentral Attendance Record'
    _order = 'auth_datetime DESC'
    
    def ensure_utc_datetime(self, dt_value):
        """
        Preserve the original datetime from the source database without any conversion
        This function now just returns the value as is to maintain the PostgreSQL format
        """
        return dt_value
        
    @api.model
    def create(self, vals):
        """Override create to ensure timestamp format consistency"""
        if 'auth_datetime' in vals and vals['auth_datetime']:
            # Always ensure auth_datetime is stored as a string
            if not isinstance(vals['auth_datetime'], str):
                from datetime import datetime
                if isinstance(vals['auth_datetime'], datetime):
                    vals['auth_datetime'] = vals['auth_datetime'].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    # Fallback - convert to string
                    vals['auth_datetime'] = str(vals['auth_datetime'])
        
        return super(HikAttendanceRecord, self).create(vals)
    
    def ensure_utc_datetime(self, dt_value):
        """
        Make sure datetime is timezone-aware using the configured timezone
        If it's not, make it timezone-aware using the config's timezone
        """
        if not dt_value:
            return dt_value
            
        if isinstance(dt_value, str):
            try:
                from dateutil.parser import parse
                dt_value = parse(dt_value)
            except Exception as e:
                _logger.error(f"Error parsing datetime: {e}")
                return dt_value
        
        if dt_value.tzinfo is None or dt_value.tzinfo.utcoffset(dt_value) is None:
            if hasattr(self, 'config_id') and self.config_id and self.config_id.timezone:
                try:
                    timezone = pytz.timezone(self.config_id.timezone)
                    dt_value = timezone.localize(dt_value)
                    # Convert to UTC since Odoo stores datetimes in UTC
                    dt_value = dt_value.astimezone(pytz.UTC)
                except Exception as e:
                    _logger.error(f"Error applying timezone {self.config_id.timezone}: {e}")
                    dt_value = pytz.UTC.localize(dt_value)
            else:
                try:
                    dt_value = pytz.UTC.localize(dt_value)
                except Exception as e:
                    _logger.error(f"Error making datetime timezone-aware: {e}")
                    
        return dt_value

    name = fields.Char(string='ID', compute='_compute_name', store=True)
    config_id = fields.Many2one('hik.central.db.config', string='Database Configuration', required=True, ondelete='cascade')
    external_id = fields.Integer(string='External ID', help='ID from the external database')
    employee_code = fields.Char(string='Employee Code', help='Employee ID from HikCentral')
    card_number = fields.Char(string='Card Number')
    person_name = fields.Char(string='Person Name')
    auth_datetime = fields.Char(string='Authentication Datetime', store=True)
    device_name = fields.Char(string='Device Name')
    direction = fields.Char(string='Direction', help='Entry or Exit')
    auth_result = fields.Char(string='Authentication Result')
    auth_type = fields.Char(string='Authentication Type')
    temperature = fields.Float(string='Temperature', digits=(5, 2))
    attendance_status = fields.Char(string='Attendance Status', help='Check-in or Check-out status from HikCentral')
    raw_data = fields.Text(string='Raw Data', help='Complete data from external database')
    
    state = fields.Selection([
        ('new', 'New'),
        ('processed', 'Processed'),
        ('error', 'Error'),
    ], string='Status', default='new', required=True)
    
    employee_id = fields.Many2one('hr.employee', string='Odoo Employee')
    attendance_id = fields.Many2one('hr.attendance', string='Odoo Attendance')
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('external_id_config_uniq', 'unique(external_id, config_id)', 'Attendance record must be unique per configuration!')
    ]
    
    @api.depends('employee_code', 'auth_datetime')
    def _compute_name(self):
        for record in self:
            if record.employee_code and record.auth_datetime:
                record.name = f"{record.employee_code} - {record.auth_datetime}"
            else:
                record.name = f"Record {record.id}"
    
    @api.model
    def auto_process_attendance_records(self):
        """
        Automatically process unprocessed attendance records:
        1. Find unprocessed records
        2. Map them to employees
        3. Create attendance records
        4. Update any open attendances
        
        This method is intended to be called by a scheduled action.
        """
        _logger.info("Starting automatic attendance processing")
        records = self.search([('state', '=', 'new')])
        
        if not records:
            _logger.info("No new attendance records to process")
            return False
            
        _logger.info(f"Found {len(records)} new attendance records to process")
        
        # Step 1: Map employees
        records.action_map_employee()
        _logger.info("Employee mapping completed")
        
        # Step 2: Create attendance records (only for records that were successfully mapped)
        mapped_records = records.filtered(lambda r: r.employee_id and r.state != 'error')
        if mapped_records:
            mapped_records.action_create_attendance()
            _logger.info(f"Attendance creation completed for {len(mapped_records)} records")
        
        # Step 3: Update any open attendances with new checkout records
        self.env['hr.attendance'].update_open_attendances()
        _logger.info("Open attendances updated with latest checkout times")
        
        processed_count = len(records.filtered(lambda r: r.state == 'processed'))
        error_count = len(records.filtered(lambda r: r.state == 'error'))
        
        _logger.info(f"Automatic attendance processing completed. Processed: {processed_count}, Errors: {error_count}")
        return True
    
    def action_map_employee(self):
        """Map attendance records to Odoo employees based on Badge ID"""
        for record in self:
            employee = self.env['hr.employee'].search([
                ('barcode', '=', record.employee_code)
            ], limit=1)
            if employee:
                record.employee_id = employee.id
            else:
                record.notes = f"{record.notes or ''}\nCould not find matching employee for Barcode {record.employee_code}"
                record.state = 'error'
    
    def action_create_attendance(self):
        """Create hr.attendance records using earliest check-in and latest check-out per employee per day"""
        from collections import defaultdict
        import pytz
        import datetime as dt
        from dateutil.parser import parse

        current_datetime_utc = dt.datetime.now()
        today = current_datetime_utc.date()

        records_by_employee_date = defaultdict(list)
        for record in self.filtered(lambda r: r.employee_id and r.state != 'processed'):
            if not record.auth_datetime:
                continue
                
            try:
                parsed_datetime = parse(record.auth_datetime)
                record_dt = parsed_datetime
                date_key = (record.employee_id.id, record_dt.date())
                records_by_employee_date[date_key].append(record)
            except Exception as e:
                record.write({
                    'state': 'error',
                    'notes': f"{record.notes or ''}\nError parsing datetime: {str(e)}"
                })
                _logger.error(f"Error parsing datetime for record {record.id}: {str(e)}")
        attendance_created = 0
        skipped_days = 0
        
        for (employee_id, date), records in records_by_employee_date.items():
            checkins = []
            checkouts = []
            unclassified = []
            
            for r in records:
                _logger.info(f"Record {r.id}: attendance_status='{r.attendance_status}'")
                
                if r.attendance_status:
                    status_lower = r.attendance_status.lower().strip()
                    
                    if ('checkin' in status_lower or 'check-in' in status_lower or 'check in' in status_lower or 
                        status_lower == 'in' or status_lower == '1'):
                        _logger.info(f"Classified as CHECK-IN based on status: '{r.attendance_status}'")
                        checkins.append(r)
                    
                    elif ('checkout' in status_lower or 'check-out' in status_lower or 'check out' in status_lower or 
                          status_lower == 'out' or status_lower == '0'):
                        _logger.info(f"Classified as CHECK-OUT based on status: '{r.attendance_status}'")
                        checkouts.append(r)
                    
                    else:
                        _logger.info(f"Unclassified based on status: '{r.attendance_status}'")
                        unclassified.append(r)
                else:
                    _logger.info(f"Unclassified due to missing attendance_status")
                    unclassified.append(r)
            
            if unclassified:
                sorted_unclassified = sorted(unclassified, key=lambda r: parse(r.auth_datetime) if r.auth_datetime else dt.datetime.min)
                
                for idx, r in enumerate(sorted_unclassified):
                    _logger.info(f"Unclassified record {idx+1}/{len(sorted_unclassified)}: {r.name}, time: {r.auth_datetime}")
                
                if not checkins or len(checkouts) > len(checkins):
                    if sorted_unclassified:
                        earliest = sorted_unclassified[0]
                        checkins.append(earliest)
                        _logger.info(f"Inferred check-in from earliest unclassified record: {earliest.name}, time: {earliest.auth_datetime}")
                        sorted_unclassified.remove(earliest)
                
                if (not checkouts or len(checkins) > len(checkouts)) and sorted_unclassified:
                    latest = sorted_unclassified[-1]
                    checkouts.append(latest)
                    _logger.info(f"Inferred check-out from latest unclassified record: {latest.name}, time: {latest.auth_datetime}")
            
            if not checkins:
                _logger.warning(f"No check-in records for employee ID {employee_id} on {date}. Skipping.")
                skipped_days += 1
                continue
                
            is_today = (date == today)
            
            use_default_checkout = False
            create_open_attendance = False
            
            if not checkouts:
                if is_today:
                    _logger.info(f"Today's attendance for employee ID {employee_id} has no check-out yet. Creating open attendance.")
                else:
                    _logger.info(f"Past day attendance for employee ID {employee_id} on {date} has no check-out. Creating open attendance.")
                
                create_open_attendance = True
                
            employee = self.env['hr.employee'].browse(employee_id)
            _logger.info(f"Processing attendance for {employee.name} on {date}. Found {len(checkins)} check-ins and {len(checkouts)} check-outs.")
            
            check_in_record = min(checkins, key=lambda r: parse(r.auth_datetime) if r.auth_datetime else dt.datetime.min)
            _logger.info(f"Selected check-in: {check_in_record.name}, time: {check_in_record.auth_datetime}, status: {check_in_record.attendance_status or 'N/A'}, direction: {check_in_record.direction or 'N/A'}")
            
            if checkouts:
                # Use the latest check-out record
                check_out_record = max(checkouts, key=lambda r: parse(r.auth_datetime) if r.auth_datetime else dt.datetime.min)
                check_out_time = check_out_record.auth_datetime
                _logger.info(f"Selected check-out: {check_out_record.name}, time: {check_out_time}, status: {check_out_record.attendance_status or 'N/A'}, direction: {check_out_record.direction or 'N/A'}")
                
                # Validate check-in is before check-out
                check_in_dt = parse(check_in_record.auth_datetime) if check_in_record.auth_datetime else dt.datetime.min
                check_out_dt = parse(check_out_time) if check_out_time else dt.datetime.max
                if check_in_dt >= check_out_dt:
                    _logger.warning(f"Check-in time is at or after check-out time for {employee.name} on {date}. Skipping.")
                    for record in checkins + checkouts:
                        record.write({
                            'state': 'error',
                            'notes': f"{record.notes or ''}\nError: Check-in time is at or after check-out time."
                        })
                    skipped_days += 1
                    continue
            else:
                # No check-out record (we'll create an open attendance)
                check_out_record = None
                check_out_time = None
            
            try:
                # Check if an attendance record already exists for this employee on this day
                existing_attendance = self.env['hr.attendance'].search([
                    ('employee_id', '=', employee_id),
                    ('check_in', '>=', dt.datetime.combine(date, dt.time.min)),
                    ('check_in', '<', dt.datetime.combine(date + dt.timedelta(days=1), dt.time.min)),
                ], limit=1)
                
                if existing_attendance:
                    _logger.warning(f"Attendance already exists for {employee.name} on {date}.")
                    
                    if check_out_record:
                        # Parse checkout times for comparison
                        new_checkout_dt = parse(check_out_time)
                        
                        if not existing_attendance.check_out:
                            _logger.info(f"Existing attendance for {employee.name} on {date} is open, will update with checkout {check_out_time}")
                            # Mark the new checkout record as being used for update
                            check_out_record.write({
                                'attendance_id': existing_attendance.id,
                                'state': 'processed',
                                'notes': f"{check_out_record.notes or ''}\nUsed to update existing open attendance."
                            })
                            self.env['hr.attendance'].update_open_attendances()
                        elif existing_attendance.check_out:
                            existing_checkout_str = existing_attendance.check_out.strftime('%Y-%m-%d %H:%M:%S')
                            existing_checkout_dt = parse(existing_checkout_str)
                            
                            if new_checkout_dt > existing_checkout_dt:
                                _logger.info(f"Found newer checkout ({check_out_time}) than existing one ({existing_checkout_str}) for {employee.name} on {date}. Updating attendance.")
                                check_out_record.write({
                                    'attendance_id': existing_attendance.id,
                                    'state': 'processed',
                                    'notes': f"{check_out_record.notes or ''}\nUsed to update existing attendance with newer checkout time."
                                })
                                
                                self.env['hr.attendance'].update_open_attendances()
                            else:
                                _logger.info(f"New checkout ({check_out_time}) is not newer than existing one ({existing_checkout_str}) for {employee.name} on {date}. Skipping update.")
                    
                    for record in checkins + ([] if not checkouts else checkouts):
                        record.write({
                            'attendance_id': existing_attendance.id,
                            'state': 'processed',
                            'notes': f"{record.notes or ''}\nLinked to existing attendance record."
                        })
                else:
                    config_timezone = check_in_record.config_id.timezone
                    if not config_timezone:
                        _logger.warning("No timezone configured, assuming UTC")
                        tz = pytz.UTC
                    else:
                        _logger.info(f"Using configured timezone: {config_timezone}")
                        tz = pytz.timezone(config_timezone)
                    
                    naive_dt = parse(check_in_record.auth_datetime)
                    aware_dt = tz.localize(naive_dt)
                    utc_dt = aware_dt.astimezone(pytz.UTC)
                    
                    naive_utc_dt = utc_dt.replace(tzinfo=None)
                    _logger.info(f"Making check-in datetime naive for Odoo: {utc_dt} -> {naive_utc_dt}")
                    
                    attendance_vals = {
                        'employee_id': employee_id,
                        'check_in': naive_utc_dt,
                    }
                    
                    # Add check_out only if it's not an open attendance
                    if not create_open_attendance and check_out_time:
                        # Convert string to datetime for hr.attendance
                        naive_checkout_dt = parse(check_out_time)
                        aware_checkout_dt = tz.localize(naive_checkout_dt)
                        utc_checkout_dt = aware_checkout_dt.astimezone(pytz.UTC)
                        # Make the checkout datetime naive as well
                        naive_utc_checkout_dt = utc_checkout_dt.replace(tzinfo=None)
                        _logger.info(f"Making check-out datetime naive for Odoo: {utc_checkout_dt} -> {naive_utc_checkout_dt}")
                        attendance_vals['check_out'] = naive_utc_checkout_dt
                    
                    # Calculate manually what the worked hours should be
                    if not create_open_attendance and check_out_time:
                        try:
                            dt_in_utc = utc_dt  # Already calculated above for check-in
                            dt_out_utc = utc_checkout_dt  # Already calculated above for checkout
                            
                            # Log the values we're using for calculation
                            _logger.info(f"Calculating worked hours using: Check-in: {dt_in_utc}, Check-out: {dt_out_utc}")
                            
                            if dt_out_utc > dt_in_utc:
                                delta_seconds = (dt_out_utc - dt_in_utc).total_seconds()
                            else:
                                # If dates are somehow reversed, swap them to get a positive value
                                _logger.warning(f"Check-out time {dt_out_utc} is before check-in time {dt_in_utc}. Using absolute difference.")
                                delta_seconds = abs((dt_out_utc - dt_in_utc).total_seconds())
                                
                            worked_hours = abs(delta_seconds / 3600.0)  # Ensure positive value
                            _logger.info(f"Calculated worked hours: {worked_hours:.2f}")
                            
                            attendance_vals['worked_hours'] = worked_hours
                            
                            _logger.info(f"Not setting overtime directly - letting Odoo compute it")
                        except Exception as e:
                            _logger.error(f"Error calculating worked hours: {e}")
                            # Don't set worked_hours if calculation fails, let Odoo compute it
                    
                    # Only skip compute for worked_hours, let Odoo compute overtime
                    attendance_vals.pop('overtime_hours', None)
                    attendance_vals.pop('validated_overtime_hours', None)
                    
                    # Create the attendance record with pre-calculated values for worked_hours only
                    attendance = self.env['hr.attendance'].with_context(skip_compute=True).create(attendance_vals)
                    
                    # Trigger a flush to ensure values are saved
                    self.env.cr.commit()
                    attendance_created += 1
                    
                    # Log whether we created a closed or open attendance
                    if create_open_attendance:
                        _logger.info(f"Created open attendance for {employee.name} on {date}")
                    else:
                        _logger.info(f"Created closed attendance for {employee.name} on {date} from {attendance_vals['check_in']} to {attendance_vals.get('check_out')}")
                    
                    # Update the check-in record
                    check_in_record.write({
                        'attendance_id': attendance.id,
                        'state': 'processed',
                    })
                    
                    # Handle check-out record or add notes based on the type of attendance we created
                    if create_open_attendance:
                        # Add a note to the check-in record that this is an open attendance
                        note_text = "\nCreated open attendance without check-out."
                        if is_today:
                            note_text += " (current day)"
                        else:
                            note_text += " (missing check-out on past day)"
                            
                        check_in_record.write({
                            'notes': f"{check_in_record.notes or ''}{note_text}"
                        })
                    elif check_out_record:
                        # Update the check-out record if it exists
                        check_out_record.write({
                            'attendance_id': attendance.id,
                            'state': 'processed',
                        })
                        
            except Exception as e:
                _logger.error(f"Error creating attendance record: {e}")
                check_in_record.write({
                    'state': 'error',
                    'notes': f"{check_in_record.notes or ''}\nError creating attendance: {str(e)}"
                })
                if check_out_record:
                    check_out_record.write({
                        'state': 'error',
                        'notes': f"{check_out_record.notes or ''}\nError creating attendance: {str(e)}"
                    })
                skipped_days += 1
                
        # Try to update any open attendances with new check-out data
        updated_open = 0
        try:
            updated_open = self.env['hr.attendance'].update_open_attendances()
        except Exception as e:
            _logger.error(f"Error updating open attendances: {e}")
            
        message = _(f'Created {attendance_created} attendance records. ')
        if updated_open:
            message += _(f'Updated {updated_open} open attendances. ')
        if skipped_days:
            message += _(f'Skipped {skipped_days} days due to errors or missing data.')
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Attendance Processing Complete'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }
    
    def action_reprocess_attendance_records(self):
        """
        Reset and reprocess all attendance records to fix timezone issues
        """
        # First, delete all existing hr.attendance records linked to hik records
        attendance_ids = self.mapped('attendance_id').ids
        if attendance_ids:
            self.env['hr.attendance'].browse(attendance_ids).unlink()
        
        # Reset all records to 'new' state
        self.write({
            'state': 'new',
            'attendance_id': False
        })
        
        # Process all records
        self.action_map_employee()
        mapped_records = self.filtered(lambda r: r.employee_id and r.state != 'error')
        if mapped_records:
            result = mapped_records.action_create_attendance()
            return result
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reprocess Complete'),
                'message': _('Attendance records have been reset and reprocessed.'),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def action_analyze_attendance_status(self):
        """
        Analyze attendance_status values in the database to help map check-in and check-out values.
        This is a debugging tool to understand what attendance_status values are being used.
        """
        # Group by attendance_status and count occurrences
        self.env.cr.execute("""
            SELECT attendance_status, COUNT(*) as count
            FROM hik_attendance_record
            GROUP BY attendance_status
            ORDER BY count DESC
        """)
        status_counts = self.env.cr.fetchall()
        
        # Prepare message
        if not status_counts:
            message = "No attendance records found."
        else:
            message = "Attendance Status Analysis:\n\n"
            for status, count in status_counts:
                status_text = status or "None/NULL"
                message += f"{status_text}: {count} records\n"
        
        # Display in a notification
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Attendance Status Analysis'),
                'message': message,
                'type': 'info',
                'sticky': True,
            }
        }
