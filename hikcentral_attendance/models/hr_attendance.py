from odoo import models, fields, api, _
from datetime import datetime, timedelta
import logging
import pytz
from dateutil.parser import parse

_logger = logging.getLogger(__name__)

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'
    
    hikcentral_record_ids = fields.One2many('hik.attendance.record', 'attendance_id', string='HikCentral Records')
    
    @api.depends('check_in', 'check_out')
    def _compute_worked_hours(self):
        """ Override compute worked hours to respect skip_compute context """
        if self.env.context.get('skip_compute'):
            return
        
        return super(HrAttendance, self)._compute_worked_hours()
    
    @api.depends('worked_hours')
    def _compute_overtime_hours(self):
        """ Let standard Odoo compute overtime hours """
        return super(HrAttendance, self)._compute_overtime_hours()
    
    @api.depends('employee_id', 'overtime_status', 'overtime_hours')
    def _compute_validated_overtime_hours(self):
        """ Let standard Odoo compute validated overtime hours """
        return super(HrAttendance, self)._compute_validated_overtime_hours()
    
    def ensure_utc_datetime(self, dt_value):
        """
        Make sure datetime is timezone-aware
        If it's not, make it timezone-aware in UTC
        """
        if not dt_value:
            return dt_value
            
        # If dt_value is a string, parse it
        if isinstance(dt_value, str):
            try:
                from dateutil.parser import parse
                dt_value = parse(dt_value)
            except Exception as e:
                _logger.error(f"Error parsing datetime: {e}")
                return dt_value
                
        # Check if the datetime is naive (no timezone info)
        if dt_value.tzinfo is None or dt_value.tzinfo.utcoffset(dt_value) is None:
            # Make it timezone-aware in UTC
            try:
                dt_value = pytz.UTC.localize(dt_value)
            except Exception as e:
                _logger.error(f"Error making datetime timezone-aware: {e}")
                
        return dt_value
    
    @api.model
    def update_open_attendances(self):
        """
        Check for open attendances and update them with check-out times if available
        This method can be called by a scheduled action or from the HikCentral attendance processing
        """
        # _logger.info("====== STARTING UPDATE ATTENDANCES PROCESS ======")
        
        # Get all attendances from today and yesterday
        from datetime import datetime, timedelta
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        
        open_attendances = self.search([
            ('check_out', '=', False),
        ])
        _logger.info(f"Found {len(open_attendances)} open attendances without checkout")
        
        # Also get recent closed attendances to check for newer checkout records
        recent_closed_attendances = self.search([
            ('check_out', '!=', False),
            ('check_in', '>=', yesterday),
        ])
        _logger.info(f"Found {len(recent_closed_attendances)} recent closed attendances to check for updates")
        
        # Combine both lists for processing
        all_attendances_to_check = open_attendances + recent_closed_attendances
        
        updated_count = 0
        
        for attendance in all_attendances_to_check:
            employee = attendance.employee_id
            check_in_time = attendance.check_in
            check_out_time = attendance.check_out
            
            _logger.info(f"Processing attendance for {employee.name}: check_in={check_in_time}, check_out={check_out_time}")
            
            if not employee or not check_in_time:
                continue
            
            from datetime import datetime
            # Convert the check_in_time to date if it's a datetime object
            if isinstance(check_in_time, datetime):
                check_in_date = check_in_time.date()
            else:
                try:
                    check_in_date = datetime.strptime(check_in_time[:10], '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    _logger.error(f"Could not parse check_in_time: {check_in_time}")
                    continue
            
            _logger.info(f"Searching for checkout records for {employee.name} after {check_in_time}")
            
            hik_records = self.env['hik.attendance.record'].search([
                ('employee_id', '=', employee.id),
                ('auth_datetime', '>', check_in_time),
            ], order='auth_datetime ASC')
            
            # _logger.info(f"Found {len(hik_records)} records for {employee.name} after check-in")
            for idx, rec in enumerate(hik_records):
                _logger.info(f"Record {idx+1}: id={rec.id}, time={rec.auth_datetime}, status={rec.attendance_status}")
            
            # Filter for checkout records based ONLY on attendance_status
            checkout_records = []
            for rec in hik_records:
                if rec.attendance_status:
                    status_lower = rec.attendance_status.lower().strip()
                    if ('checkout' in status_lower or 'check-out' in status_lower or 
                        'check out' in status_lower or status_lower == 'out' or 
                        status_lower == '0'):
                        checkout_records.append(rec)
                        _logger.info(f"Record {rec.id} identified as checkout by status: '{rec.attendance_status}'")
            
            checkout_records.sort(key=lambda r: r.auth_datetime, reverse=True)
            
            # Use the latest checkout record (first after sorting)
            hik_records = checkout_records[:1]
            
            if checkout_records:
                checkout_times = [f"{rec.auth_datetime} (id:{rec.id})" for rec in checkout_records]
                _logger.info(f"Checkout times found (sorted latest first): {checkout_times}")
                _logger.info(f"Selected {len(hik_records)} checkout records - using the latest checkout: {hik_records[0].auth_datetime if hik_records else 'None'}")
            else:
                _logger.info(f"No checkout records found for this employee today")
            
            if hik_records:
                checkout_record = hik_records[0]
                
                # Get checkout date 
                auth_datetime = checkout_record.auth_datetime
                
                # Parse the date from the string datetime
                from datetime import datetime
                try:
                    if isinstance(auth_datetime, datetime):
                        checkout_date = auth_datetime.date()
                        checkout_hour = auth_datetime.hour
                    else:
                        # Parse the string format
                        checkout_date = datetime.strptime(auth_datetime[:10], '%Y-%m-%d').date()
                        checkout_hour = int(auth_datetime[11:13]) if len(auth_datetime) > 13 else 0
                except (ValueError, TypeError, IndexError):
                    _logger.error(f"Could not parse auth_datetime: {auth_datetime}")
                    continue
                    
                same_day = (checkout_date == check_in_date)
                next_day_early_morning = (checkout_date == check_in_date + timedelta(days=1) and checkout_hour < 12)
                
                if check_out_time:
                    parsed_auth_dt = None
                    if isinstance(auth_datetime, str):
                        try:
                            from dateutil.parser import parse
                            parsed_auth_dt = parse(auth_datetime)
                        except Exception as e:
                            _logger.error(f"Error parsing auth_datetime for comparison: {e}")
                            continue
                    else:
                        parsed_auth_dt = auth_datetime
                    
                    # Now compare the two datetime objects
                    if parsed_auth_dt <= check_out_time:
                        _logger.info(f"Skipping update for {employee.name} - found checkout ({parsed_auth_dt}) is not newer than existing checkout ({check_out_time})")
                        continue
                    else:
                        _logger.info(f"Found newer checkout ({parsed_auth_dt}) than existing checkout ({check_out_time}) - will update")
                
                if same_day or next_day_early_morning:
                    _logger.info(f"Valid checkout found for {employee.name}. Same day: {same_day}, Next day early morning: {next_day_early_morning}")
                    
                    checkout_str = checkout_record.auth_datetime
                    _logger.info(f"Processing checkout datetime: {checkout_str}")
                    
                    try:
                        config_timezone = checkout_record.config_id.timezone
                        _logger.info(f"Using configured timezone: {config_timezone}")
                        
                        if isinstance(checkout_str, str):
                            try:
                                naive_dt = datetime.strptime(checkout_str, '%Y-%m-%d %H:%M:%S')
                            except ValueError:
                                try:
                                    naive_dt = datetime.strptime(checkout_str, '%Y-%m-%d %H:%M:%S.%f')
                                except ValueError:
                                    # Use a more flexible parser as last resort
                                    from dateutil.parser import parse
                                    naive_dt = parse(checkout_str)
                        else:
                            naive_dt = checkout_str
                        
                        _logger.info(f"Parsed checkout datetime: {naive_dt}")
                        
                        if config_timezone:
                            tz = pytz.timezone(config_timezone)
                            aware_dt = tz.localize(naive_dt)
                            utc_dt = aware_dt.astimezone(pytz.UTC)
                        else:
                            # If no timezone configured, assume UTC
                            _logger.warning("No timezone configured, assuming UTC")
                            utc_dt = pytz.UTC.localize(naive_dt)
                            
                        _logger.info(f"Converted to UTC: {utc_dt}")
                    except Exception as e:
                        _logger.error(f"Error processing checkout datetime: {e}")
                        import traceback
                        _logger.error(traceback.format_exc())
                        continue
                    
                    check_in_dt = attendance.check_in
                    
                    if check_in_dt.tzinfo is None or check_in_dt.tzinfo.utcoffset(check_in_dt) is None:
                        # It's naive, assume it's in UTC and make it aware
                        _logger.info("Check-in datetime is naive, making it timezone-aware")
                        check_in_dt = pytz.UTC.localize(check_in_dt)
                    
                    if utc_dt > check_in_dt:
                        delta_seconds = (utc_dt - check_in_dt).total_seconds()
                    else:
                        # If dates are somehow reversed, swap them to get a positive value
                        _logger.warning(f"Check-out time {utc_dt} is before check-in time {check_in_dt}. Using absolute difference.")
                        delta_seconds = abs((utc_dt - check_in_dt).total_seconds())
                        
                    _logger.info(f"Calculated worked hours: {delta_seconds/3600.0:.2f} hours from {check_in_dt} to {utc_dt}")
                    worked_hours = abs(delta_seconds / 3600.0)  # Ensure positive value
                    
                    # Odoo expects naive datetimes (without timezone info)
                    naive_utc_dt = utc_dt.replace(tzinfo=None)
                    _logger.info(f"Making datetime naive for Odoo: {utc_dt} -> {naive_utc_dt}")
                    
                    # Write all values at once
                    vals = {
                        'check_out': naive_utc_dt,
                        'worked_hours': worked_hours
                    }
                    
                    _logger.info(f"Not setting overtime directly - letting Odoo compute it")
                    
                    # _logger.info(f"Writing attendance values: {vals}")
                    
                    attendance.with_context(skip_compute=True).write(vals)
                    
                    # Force compute overtime after setting checkout and worked_hours
                    attendance._compute_overtime_hours()
                    attendance._compute_validated_overtime_hours()
                    
                    # Trigger a flush to ensure values are saved
                    self.env.cr.commit()
                    
                    # Mark the HIK record as processed and link it to this attendance
                    checkout_record.write({
                        'attendance_id': attendance.id,
                        'state': 'processed',
                    })
                    
                    # Record the update in the message log for this attendance
                    msg = f"Attendance updated with checkout time {checkout_record.auth_datetime}"
                    if check_out_time:
                        msg += f" (replacing previous checkout time {check_out_time})"
                    attendance.message_post(body=msg)
                    
                    _logger.info(f"Updated attendance for employee {employee.name} with check-out time {checkout_record.auth_datetime}")
                    updated_count += 1
        
        return updated_count
    
    @api.model
    def auto_checkout_missing_employees(self):
        """
        Run at the end of each workday (11:30 PM) to automatically check out employees 
        who forgot to register their checkout.
        
        This method:
        1. Finds all open attendances for the current day
        2. Automatically sets the checkout time to 17:30 (5:30 PM) on the same day as the check-in
        3. Sends email notifications to affected employees
        """
        _logger.info("Starting automatic checkout for employees who forgot to check out (using 17:30 as checkout time)")
        
        # Get all open attendances from today
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Find open attendances that started today
        open_attendances = self.search([
            ('check_in', '>=', today_start),
            ('check_out', '=', False),
        ])
        
        _logger.info(f"Found {len(open_attendances)} open attendances without checkout")
        
        if not open_attendances:
            _logger.info("No open attendances found for today. Nothing to process.")
            return 0
        
        # Get the configured timezone from HikCentral DB Config
        # We'll use the first active configuration's timezone
        config = self.env['hik.central.db.config'].search([('active', '=', True)], limit=1)
        if not config:
            _logger.warning("No active HikCentral configuration found. Using UTC timezone.")
            config_timezone = 'UTC'
        else:
            config_timezone = config.timezone
            
        _logger.info(f"Using timezone from configuration: {config_timezone}")
        tz = pytz.timezone(config_timezone)
            
        auto_checked_count = 0
        
        # Hard-coded checkout time of 17:30 (5:30 PM)
        CHECKOUT_HOUR = 17
        CHECKOUT_MINUTE = 30
        
        for attendance in open_attendances:
            employee = attendance.employee_id
            if not employee:
                continue
                
            _logger.info(f"Processing automatic checkout for employee: {employee.name}")
            
            # Get check-in time - this is UTC in Odoo database
            check_in_time = attendance.check_in
            _logger.info(f"Original check-in time (UTC): {check_in_time}")
            
            # Make the check-in time timezone-aware (it's stored as naive in UTC)
            if check_in_time.tzinfo is None:
                check_in_time = pytz.UTC.localize(check_in_time)
            
            # Convert check-in time to configured timezone
            local_check_in = check_in_time.astimezone(tz)
            _logger.info(f"Local check-in time ({config_timezone}): {local_check_in}")
            
            # Create the checkout time in the local timezone (17:30 on the same day)
            local_checkout_time = local_check_in.replace(
                hour=CHECKOUT_HOUR,
                minute=CHECKOUT_MINUTE,
                second=0,
                microsecond=0
            )
            _logger.info(f"Local checkout time ({config_timezone}): {local_checkout_time} (17:30)")
            
            # Ensure checkout time is after check-in time (in the local timezone)
            if local_checkout_time <= local_check_in:
                # If 17:30 is before check-in (employee checked in after 5:30 PM),
                # set checkout to check-in time + 8 hours (standard workday)
                local_checkout_time = local_check_in + timedelta(hours=8)
                _logger.info(f"Standard 17:30 checkout would be before check-in. Using check-in + 8 hours: {local_checkout_time}")
                
            # Convert the local checkout time back to UTC for storage in Odoo
            utc_checkout_time = local_checkout_time.astimezone(pytz.UTC)
            _logger.info(f"UTC checkout time: {utc_checkout_time}")
            
            # Make it naive for Odoo storage
            checkout_time = utc_checkout_time.replace(tzinfo=None)
            _logger.info(f"Final naive checkout time for Odoo: {checkout_time}")
            
            # Get the original naive check_in_time for delta calculation
            original_check_in = attendance.check_in
            _logger.info(f"Original naive check_in time for delta calculation: {original_check_in}")
            
            # Calculate worked hours using naive datetimes
            delta_seconds = (checkout_time - original_check_in).total_seconds()
            worked_hours = delta_seconds / 3600.0
            
            # Update the attendance record with checkout time and worked hours
            vals = {
                'check_out': checkout_time,
                'worked_hours': worked_hours
            }
            
            _logger.info(f"Setting checkout for {employee.name} to {checkout_time} (with {worked_hours:.2f} hours worked)")
            
            try:
                # Update attendance with checkout time and worked hours
                attendance.with_context(skip_compute=True).write(vals)
                
                # Force compute overtime after setting checkout and worked_hours
                attendance._compute_overtime_hours()
                attendance._compute_validated_overtime_hours()
                
                # Post a note in the chatter about this automatic checkout
                attendance.message_post(
                    body=_(f"System automatically registered checkout at {checkout_time} "
                           "because employee forgot to check out.")
                )
                
                auto_checked_count += 1
                
                # Send email notification to employee
                if employee.work_email:
                    # Prepare email template
                    mail_template = self.env.ref('mail.mail_notification_paynow', raise_if_not_found=False)
                    if mail_template:
                        # Get local time for display in email
                        local_time = checkout_time
                        if employee.tz:
                            # Convert to employee's timezone if available
                            try:
                                user_tz = pytz.timezone(employee.tz)
                                # checkout_time is naive, so we need to make it aware first (as UTC)
                                utc_time = pytz.utc.localize(checkout_time)
                                local_time = utc_time.astimezone(user_tz)
                            except Exception as e:
                                _logger.error(f"Error converting time to employee timezone: {e}")
                        
                        formatted_time = local_time.strftime("%I:%M %p")
                        formatted_date = local_time.strftime("%B %d, %Y")
                        
                        # Render and send email
                        subject = _("Automatic Checkout Notification")
                        body = _("""
                        <p>Dear %s,</p>
                        <p>The system has noticed that you did not register your checkout today (%s).</p>
                        <p>An automatic checkout has been recorded for you at <strong>%s</strong>.</p>
                        <p>If this was a mistake or you have any questions, please contact HR.</p>
                        <p>Thank you,<br/>HR Department</p>
                        """) % (employee.name, formatted_date, formatted_time)
                        
                        mail_values = {
                            'email_from': self.env.company.email or "noreply@example.com",
                            'email_to': employee.work_email,
                            'subject': subject,
                            'body_html': body,
                            'auto_delete': True,
                        }
                        
                        try:
                            mail_id = self.env['mail.mail'].create(mail_values)
                            mail_id.send()
                            _logger.info(f"Automatic checkout notification email sent to {employee.name} at {employee.work_email}")
                        except Exception as e:
                            _logger.error(f"Error sending checkout notification email: {e}")
                else:
                    _logger.warning(f"Cannot send notification email to {employee.name} - no work email defined")
                    
            except Exception as e:
                _logger.error(f"Error processing automatic checkout for {employee.name}: {e}")
                import traceback
                _logger.error(traceback.format_exc())
        
        return auto_checked_count
