from odoo import models, fields, api, _
from odoo.exceptions import UserError
import psycopg2
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

class HikCentralDbConfig(models.Model):
    _name = 'hik.central.db.config'
    _description = 'HikCentral Database Configuration'
    _rec_name = 'name'

    name = fields.Char('Configuration Name', required=True)
    host = fields.Char('Database Host', required=True)
    port = fields.Integer('Database Port', required=True, default=5432)
    database = fields.Char('Database Name', required=True)
    schema = fields.Char('Schema', default='public')
    table_name = fields.Char('Table Name', required=True, default='attendance_data')
    username = fields.Char('Database Username', required=True)
    password = fields.Char('Database Password', required=True)
    timezone = fields.Selection([
        ('Asia/Karachi', 'Pakistan (Asia/Karachi)'),
        ('UTC', 'UTC'),
        ('Asia/Kolkata', 'India (Asia/Kolkata)'),
        ('Asia/Dubai', 'UAE (Asia/Dubai)'),
        ('Europe/London', 'UK (Europe/London)'),
        ('US/Eastern', 'US Eastern'),
        ('US/Central', 'US Central'),
        ('US/Pacific', 'US Pacific'),
        ('Australia/Sydney', 'Australia (Sydney)'),
    ], string='Timezone', required=True, default='Asia/Karachi',
       help='Timezone to use for the database connection. This ensures timestamps are preserved correctly.')
    active = fields.Boolean('Active', default=True)
    last_sync_date = fields.Datetime('Last Synchronization Date')
    
    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Configuration name must be unique!')
    ]
    
    def test_connection(self):
        self.ensure_one()
        try:
            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.username,
                password=self.password,
                options=f"-c timezone={self.timezone}"  # Use configured timezone
            )
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {self.schema}.{self.table_name}")
            record_count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Successful'),
                    'message': _('Successfully connected to the external database. Found %s records.') % record_count,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            _logger.error("Database connection error: %s", e)
            raise UserError(_('Connection failed: %s') % e)
    
    def fetch_attendance_data(self):
        """
        Fetch attendance data from the external database.
        This method is called by the cron job.
        """
        total_imported = 0
        for config in self.search([('active', '=', True)]):
            try:
                _logger.info(f"Starting attendance data synchronization from {config.name}")
                
                # Connect to the database using configured timezone to preserve original timestamps
                conn = psycopg2.connect(
                    host=config.host,
                    port=config.port,
                    dbname=config.database,
                    user=config.username,
                    password=config.password,
                    options=f"-c timezone={config.timezone}"  # Use configured timezone
                )
                cursor = conn.cursor()
                
                # Prepare the query - CRITICAL: Cast authdatetime to text to preserve format exactly
                query = f"""
                SELECT id, employeeid, firstname, lastname, personname, 
                       persongroup, cardno, authdate, authtime, devicename, 
                       devicesn, resourcename, readername, direction, authresult, 
                       authtype, temperaturestatus, maskstatus, authdatetime::text, 
                       temperature, attendance_status
                FROM {config.schema}.{config.table_name}
                """
                
                # Add filter by last_sync_date if available
                if config.last_sync_date:
                    # CRITICAL: Format the datetime to EXACTLY match the PostgreSQL database format 
                    # This ensures consistent comparison with the PostgreSQL timestamps
                    formatted_date = config.last_sync_date.strftime('%Y-%m-%d %H:%M:%S')
                    query += f" WHERE authdatetime::text > '{formatted_date}'"
                    _logger.info(f"Filtering records after {formatted_date}")
                else:
                    _logger.info("No last_sync_date set, fetching all records")
                
                # Order by auth datetime and set a reasonable batch size
                # Using 1000 as default batch size, can be adjusted based on system capacity
                query += " ORDER BY authdatetime DESC LIMIT 1000"
                
                _logger.info(f"Executing query: {query}")
                cursor.execute(query)
                records = cursor.fetchall()
                
                _logger.info(f"Query returned {len(records)} records")
                
                if records:
                    # Get column names
                    column_names = [desc[0] for desc in cursor.description]
                    _logger.info(f"Column names: {column_names}")
                    
                    # Process records
                    attendance_record_model = self.env['hik.attendance.record']
                    imported_count = 0
                    
                    for record in records:
                        # Create a dictionary of column_name: value
                        record_dict = dict(zip(column_names, record))
                        _logger.info(f"Processing record: {record_dict['id']}")
                        
                        # Check if record already exists
                        existing_record = attendance_record_model.search([
                            ('external_id', '=', record_dict['id']),
                            ('config_id', '=', config.id)
                        ], limit=1)
                        
                        if not existing_record:
                            _logger.info(f"Record {record_dict['id']} is new, creating in Odoo")
                            # Get person name - combine firstname/lastname if personname is empty
                            person_name = record_dict['personname']
                            if not person_name and (record_dict['firstname'] or record_dict['lastname']):
                                person_name = f"{record_dict.get('firstname', '')} {record_dict.get('lastname', '')}".strip()
                            
                            # Create new record
                            # CRITICAL: Use the timestamp EXACTLY as it comes from PostgreSQL
                            # This ensures we preserve the original timestamp format and timezone
                            auth_datetime = record_dict['authdatetime']
                            
                            new_record = attendance_record_model.create({
                                'config_id': config.id,
                                'external_id': record_dict['id'],
                                'employee_code': record_dict['employeeid'],
                                'person_name': person_name,
                                'card_number': record_dict['cardno'],
                                'auth_datetime': auth_datetime,
                                'device_name': record_dict['devicename'],
                                'direction': record_dict['direction'],
                                'auth_result': record_dict['authresult'],
                                'auth_type': record_dict['authtype'],
                                'temperature': record_dict['temperature'],
                                'attendance_status': record_dict['attendance_status'],
                                'raw_data': str(record_dict),
                                'state': 'new',
                            })
                            _logger.info(f"Created record with ID: {new_record.id}")
                            imported_count += 1
                        else:
                            _logger.info(f"Record {record_dict['id']} already exists, skipping")
                    
                    total_imported += imported_count
                    _logger.info(f"Successfully imported {imported_count} attendance records")
                    
                    # Update the last sync date when records are imported
                    if imported_count > 0:
                        # Get the most recent authdatetime from the imported records
                        # Note that records are already sorted by authdatetime DESC
                        auth_datetime_index = column_names.index('authdatetime')
                        most_recent_record = records[0]  # First record is most recent due to ORDER BY
                        most_recent_datetime = most_recent_record[auth_datetime_index]
                        
                        # Update the last sync date to the most recent record's datetime
                        # Store the datetime as-is without timezone conversion to preserve format
                        _logger.info(f"Updating last_sync_date to {most_recent_datetime}")
                        config.last_sync_date = most_recent_datetime
                else:
                    _logger.info("No records found to import")
                
                cursor.close()
                conn.close()
                
            except Exception as e:
                _logger.error(f"Error during attendance data synchronization from {config.name}: {str(e)}")
                # Also print the traceback for debugging
                import traceback
                _logger.error(traceback.format_exc())
        
        return total_imported
    
    def action_reset_sync_date(self):
        """
        Reset the last synchronization date to allow re-importing of attendance data
        """
        self.ensure_one()
        
        previous_date = self.last_sync_date
        self.last_sync_date = False
        
        message = _('Last synchronization date has been reset.')
        if previous_date:
            message = _(f'Last synchronization date has been reset (was: {previous_date}).')
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Date Reset'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }
    
    def action_set_sync_date_wizard(self):
        """
        Open a wizard to set the sync date to a specific date
        """
        self.ensure_one()
        return {
            'name': _('Set Synchronization Date'),
            'type': 'ir.actions.act_window',
            'res_model': 'hik.set.sync.date.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_config_id': self.id, 'default_current_date': self.last_sync_date}
        }
        
    def action_fetch_all_attendance(self):
        """
        Manual action to fetch ALL attendance data, including historical records
        """
        try:
            # First, show a preliminary message to the user
            self.env['bus.bus']._sendone(
                self.env.user.partner_id, 
                'simple_notification', 
                {
                    'title': _('Import Started'),
                    'message': _('Starting full attendance import. This may take several minutes. Please wait...'),
                    'type': 'info',
                    'sticky': True
                }
            )
            
            # Check connection before starting import
            try:
                conn = psycopg2.connect(
                    host=self.host,
                    port=self.port,
                    dbname=self.database,
                    user=self.username,
                    password=self.password
                )
                cursor = conn.cursor()
                cursor.execute(f"SELECT COUNT(*) FROM {self.schema}.{self.table_name}")
                source_count = cursor.fetchone()[0]
                cursor.close()
                conn.close()
            except Exception as e:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Error'),
                        'message': _(f'Could not connect to source database: {str(e)}'),
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Show user that this won't affect the sync date
            _logger.info("Running full import (won't affect last sync date)")
            
            # Start the actual import
            imported_count = self.fetch_all_attendance_data()
            
            # Get the current count in Odoo database
            record_count = self.env['hik.attendance.record'].search_count([])
            
            if imported_count > 0:
                message = _(f'Full attendance import completed. {imported_count} new records imported.\n\n'
                            f'Total records in source database: {source_count}\n'
                            f'Total records now in Odoo: {record_count}\n\n'
                            f'Note: Last sync date was not changed by this operation.')
                record_type = 'success'
            else:
                message = _(f'No new records were imported.\n\n'
                            f'Total records in source database: {source_count}\n'
                            f'Total records in Odoo: {record_count}\n\n'
                            f'Possible reasons:\n'
                            f'- All records already exist in Odoo\n'
                            f'- Source database is empty\n'
                            f'- Source table structure is not compatible\n\n'
                            f'Note: Last sync date was not changed by this operation.')
                record_type = 'info'
                
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Full Attendance Import'),
                    'message': message,
                    'type': record_type,
                    'sticky': True,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                        'followed_by': {
                            'type': 'ir.actions.client',
                            'tag': 'reload',
                        }
                    }
                }
            }
        except Exception as e:
            import traceback
            _logger.error(traceback.format_exc())
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _(f'Error importing attendance data: {str(e)}'),
                    'type': 'danger',
                    'sticky': True,
                }
            }
    
    def ensure_utc_datetime(self, dt_value):
        """
        Preserve the original datetime from the source database
        We use the configured timezone to maintain consistency with the source
        """
        if not dt_value:
            return dt_value
            
        # Return the datetime value as-is without timezone conversion
        # This preserves the exact datetime format from the PostgreSQL source
        return dt_value
        
    def action_analyze_source_database(self):
        """
        Analyze the source database structure and provide details about available tables and columns.
        This is a diagnostic tool to help troubleshoot connection or import issues.
        """
        self.ensure_one()
        try:
            # Connect to the database
            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.username,
                password=self.password,
                options=f"-c timezone={self.timezone}"  # Use configured timezone
            )
            cursor = conn.cursor()
            
            # Get list of tables in the schema
            cursor.execute(f"""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = '{self.schema}'
                ORDER BY table_name
            """)
            tables = [table[0] for table in cursor.fetchall()]
            
            # Get detailed info about the target table
            table_info = "Table not found"
            column_info = "No columns found"
            sample_data = "No data available"
            
            if self.table_name in tables:
                # Get column information
                cursor.execute(f"""
                    SELECT column_name, data_type, is_nullable 
                    FROM information_schema.columns 
                    WHERE table_schema = '{self.schema}' 
                    AND table_name = '{self.table_name}'
                    ORDER BY ordinal_position
                """)
                columns = cursor.fetchall()
                
                column_info = "\n".join([f"- {col[0]} ({col[1]}, {'NULL' if col[2] == 'YES' else 'NOT NULL'})" for col in columns])
                
                # Get row count
                cursor.execute(f"SELECT COUNT(*) FROM {self.schema}.{self.table_name}")
                row_count = cursor.fetchone()[0]
                table_info = f"Found table '{self.table_name}' with {row_count} rows"
                
                # Get sample data (first 5 rows)
                if row_count > 0:
                    cursor.execute(f"SELECT * FROM {self.schema}.{self.table_name} LIMIT 5")
                    rows = cursor.fetchall()
                    column_names = [desc[0] for desc in cursor.description]
                    
                    sample_rows = []
                    for row in rows:
                        row_data = []
                        for i, value in enumerate(row):
                            if value is not None:
                                if isinstance(value, (bytes, bytearray)):
                                    value_str = "<binary data>"
                                else:
                                    value_str = str(value)
                                    if len(value_str) > 50:
                                        value_str = value_str[:47] + "..."
                            else:
                                value_str = "NULL"
                            row_data.append(f"{column_names[i]}: {value_str}")
                        sample_rows.append("{\n  " + ",\n  ".join(row_data) + "\n}")
                    
                    sample_data = "Sample data (first 5 rows):\n\n" + "\n\n".join(sample_rows)
            
            cursor.close()
            conn.close()
            
            # Build diagnostic message
            message = f"""Database Structure Analysis
            
Host: {self.host}
Database: {self.database}
Schema: {self.schema}

Tables in schema ({len(tables)}):
{', '.join(tables)}

Target Table:
{table_info}

Columns:
{column_info}

{sample_data}
"""
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Database Analysis'),
                    'message': message,
                    'type': 'info',
                    'sticky': True,
                }
            }
        
        except Exception as e:
            import traceback
            _logger.error(traceback.format_exc())
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Analysis Error'),
                    'message': _(f'Error analyzing database: {str(e)}'),
                    'type': 'danger',
                    'sticky': True,
                }
            }
    
    def fetch_all_attendance_data(self):
        """
        Fetch ALL attendance data from the external database, ignoring the last sync date.
        This is a complete reimplementation of the fetch logic to ensure we get all records.
        """
        # Use self instead of looping through configs to better handle transactions
        self.ensure_one()  # Make sure we only process one config at a time
        total_imported = 0
        cr = self.env.cr  # Get database cursor for explicit transaction control
        
        try:
            _logger.info(f"Starting full attendance data synchronization from {self.name}")
            
            # Connect to the database
            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.username,
                password=self.password,
                options=f"-c timezone={self.timezone}"  # Use configured timezone
            )
            cursor = conn.cursor()
            
            # Get total number of records for planning
            cursor.execute(f"SELECT COUNT(*) FROM {self.schema}.{self.table_name}")
            total_count = cursor.fetchone()[0]
            _logger.info(f"Total records in source database: {total_count}")
            
            if total_count == 0:
                _logger.info("No records found in source database")
                cursor.close()
                conn.close()
                return 0
                
            # First, get column information to ensure we have the right fields
            cursor.execute(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = '{self.schema}' 
                AND table_name = '{self.table_name}'
            """)
            db_columns = [col[0] for col in cursor.fetchall()]
            _logger.info(f"Columns in source table: {db_columns}")
            
            # Prepare the query - with NO filters at all
            query = f"""
            SELECT * 
            FROM {self.schema}.{self.table_name}
            ORDER BY id
            """
            
            # Process in smaller batches to handle large data volumes
            batch_size = 1000  # Reduced batch size for better control
            offset = 0
            
            # Get all attendance records for this config to avoid duplicates
            existing_external_ids = set(self.env['hik.attendance.record'].search([
                ('config_id', '=', self.id)
            ]).mapped('external_id'))
            _logger.info(f"Found {len(existing_external_ids)} existing records to avoid duplicates")
            
            while True:
                batch_query = f"{query} LIMIT {batch_size} OFFSET {offset}"
                _logger.info(f"Executing batch query with offset {offset}")
                cursor.execute(batch_query)
                records = cursor.fetchall()
                
                if not records:
                    _logger.info(f"No more records to fetch at offset {offset}")
                    break
                    
                _logger.info(f"Batch query returned {len(records)} records")
                
                # Get column names only once at the beginning
                if offset == 0:
                    column_names = [desc[0] for desc in cursor.description]
                    _logger.info(f"Column names from query: {column_names}")
                    
                    # Verify we have the id column
                    if 'id' not in column_names:
                        _logger.error(f"Required column 'id' not found in source table")
                        raise ValueError("Required column 'id' not found in source table")
                
                # Process records
                attendance_record_model = self.env['hik.attendance.record']
                imported_batch_count = 0
                
                for record in records:
                    # Create a dictionary of column_name: value
                    record_dict = dict(zip(column_names, record))
                    
                    # Skip if this record already exists in our system
                    if str(record_dict['id']) in existing_external_ids:
                        _logger.debug(f"Record {record_dict['id']} already exists, skipping")
                        continue
                        
                    _logger.debug(f"Processing record: {record_dict['id']}")
                    
                    # Get data with safe fallbacks
                    try:
                        # Basic required fields
                        external_id = record_dict.get('id')
                        if not external_id:
                            _logger.warning(f"Skipping record with missing ID")
                            continue
                            
                        # Try to get employee code from various possible field names
                        employee_code = None
                        for field in ['employeeid', 'employee_id', 'employee_code', 'person_id']:
                            if field in record_dict and record_dict[field]:
                                employee_code = record_dict[field]
                                break
                                
                        if not employee_code:
                            _logger.warning(f"Record {external_id} has no employee code, using ID as fallback")
                            employee_code = str(external_id)
                            
                        # Person name with fallbacks
                        person_name = record_dict.get('personname')
                        if not person_name:
                            # Try firstname/lastname combination
                            first_name = record_dict.get('firstname', '')
                            last_name = record_dict.get('lastname', '')
                            if first_name or last_name:
                                person_name = f"{first_name} {last_name}".strip()
                            else:
                                person_name = f"Person {employee_code}"
                                
                        # Authentication date and time
                        auth_datetime = record_dict.get('authdatetime')
                        if not auth_datetime:
                            # Try to combine authdate and authtime if available
                            auth_date = record_dict.get('authdate')
                            auth_time = record_dict.get('authtime')
                            if auth_date and auth_time:
                                try:
                                    from datetime import datetime
                                    auth_datetime = datetime.combine(auth_date, auth_time)
                                except Exception as e:
                                    _logger.warning(f"Failed to combine auth_date and auth_time: {e}")
                            
                        if not auth_datetime:
                            _logger.warning(f"Record {external_id} has no authentication datetime, skipping")
                            continue
                            
                        # Use the datetime as-is without conversion to preserve the PostgreSQL format
                        # auth_datetime is now preserved without timezone conversion
                        
                        # Optional fields with fallbacks
                        card_number = record_dict.get('cardno', '')
                        device_name = record_dict.get('devicename', '')
                        direction = record_dict.get('direction', '')
                        auth_result = record_dict.get('authresult', '')
                        auth_type = record_dict.get('authtype', '')
                        temperature = record_dict.get('temperature', 0.0)
                        attendance_status = record_dict.get('attendance_status', '')
                        
                        # Create new record
                        new_record = attendance_record_model.create({
                            'config_id': self.id,
                            'external_id': str(external_id),  # Convert to string to be safe
                            'employee_code': str(employee_code),  # Convert to string to be safe
                            'person_name': person_name,
                            'card_number': card_number,
                            'auth_datetime': auth_datetime,
                            'device_name': device_name,
                            'direction': direction,
                            'auth_result': auth_result,
                            'auth_type': auth_type,
                            'temperature': temperature,
                            'attendance_status': attendance_status,
                            'raw_data': str(record_dict),
                            'state': 'new',
                        })
                        
                        # Add to existing IDs set to avoid importing again in next batch
                        existing_external_ids.add(str(external_id))
                        
                        imported_batch_count += 1
                    except Exception as e:
                        _logger.error(f"Error processing record {record_dict.get('id', 'unknown')}: {e}")
                        continue
                
                total_imported += imported_batch_count
                _logger.info(f"Batch imported {imported_batch_count} records. Total so far: {total_imported}")
                
                # Commit transaction after each batch to avoid locks and timeouts
                self.env.cr.commit()
                
                # Move to next batch
                offset += batch_size
                
                # If we imported fewer records than the batch size, we're done
                if len(records) < batch_size:
                    break
            
            # No need to update last_sync_date after full import
            if total_imported > 0:
                _logger.info(f"Full import completed. Total records imported: {total_imported}")
            else:
                _logger.info("No records imported during full import")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            _logger.error(f"Error during full attendance data synchronization from {self.name}: {str(e)}")
            import traceback
            _logger.error(traceback.format_exc())
        
        return total_imported

    def action_fetch_attendance(self):
        """
        Manual action to fetch attendance data
        """
        try:
            imported_count = self.fetch_attendance_data()
            
            message = _(f'Attendance import completed. {imported_count} new records imported.')
            record_type = 'success'
            
            # If no records were imported, provide a more detailed message
            if imported_count == 0:
                record_count = self.env['hik.attendance.record'].search_count([])
                message = _(f'No new records were imported. Total records in database: {record_count}')
                record_type = 'info'
                
            # Automatically reload the attendance records list view
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Attendance Import'),
                    'message': message,
                    'type': record_type,
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                        'followed_by': {
                            'type': 'ir.actions.client',
                            'tag': 'reload',
                        }
                    }
                }
            }
        except Exception as e:
            import traceback
            _logger.error(traceback.format_exc())
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _(f'Error importing attendance data: {str(e)}'),
                    'type': 'danger',
                    'sticky': True,
                }
            }
