"""
Table Retriever for FinSyntra RAG
Handles CSV and structured data with proper normalization and formatting
"""
import csv
import json
import sqlite3
import logging
from typing import Dict, Any, Optional, List, Tuple, Union
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
from datetime import datetime
import re

from src.config.feature_flags import is_feature_enabled

logger = logging.getLogger(__name__)

@dataclass
class TableRow:
    """Represents a row from a structured table"""
    row_id: str
    data: Dict[str, Any]
    source_file: str
    chunk_id: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

@dataclass
class TableSchema:
    """Represents the schema of a structured table"""
    table_name: str
    columns: List[str]
    data_types: Dict[str, str]
    constraints: Dict[str, Any]
    source_file: str
    last_updated: datetime = None
    
    def __post_init__(self):
        if self.last_updated is None:
            self.last_updated = datetime.now()

class TableRetriever:
    """
    Retrieves and formats structured data from CSV and other tabular sources
    Provides normalized access to employee records and other structured data
    """
    
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.connection = None
        self.tables: Dict[str, TableSchema] = {}
        
        if is_feature_enabled('ENABLE_TABLE_RETRIEVER'):
            self._initialize_database()
        
        logger.info("TableRetriever initialized")
    
    def _initialize_database(self) -> None:
        """Initialize SQLite database for table storage"""
        try:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
            
            # Create tables table
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS table_schemas (
                    table_name TEXT PRIMARY KEY,
                    columns TEXT,
                    data_types TEXT,
                    constraints TEXT,
                    source_file TEXT,
                    last_updated TEXT
                )
            """)
            
            # Create table data table
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS table_data (
                    table_name TEXT,
                    row_id TEXT,
                    data TEXT,
                    chunk_id TEXT,
                    metadata TEXT,
                    PRIMARY KEY (table_name, row_id)
                )
            """)
            
            self.connection.commit()
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            self.connection = None
    
    def load_csv_file(self, file_path: str, table_name: Optional[str] = None) -> bool:
        """
        Load a CSV file into the table retriever
        Returns True if successful, False otherwise
        """
        if not is_feature_enabled('ENABLE_TABLE_RETRIEVER'):
            return False
        
        if not self.connection:
            logger.error("Database not initialized")
            return False
        
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return False
            
            # Generate table name if not provided
            if not table_name:
                table_name = file_path.stem.lower().replace(' ', '_')
            
            # Read CSV with pandas for better handling
            df = pd.read_csv(file_path)
            
            # Normalize column names
            df.columns = [self._normalize_column_name(col) for col in df.columns]
            
            # Infer data types
            data_types = self._infer_data_types(df)
            
            # Create table schema
            schema = TableSchema(
                table_name=table_name,
                columns=list(df.columns),
                data_types=data_types,
                constraints={},
                source_file=str(file_path)
            )
            
            # Store schema
            self.tables[table_name] = schema
            self._store_schema(schema)
            
            # Store data rows
            self._store_table_data(table_name, df)
            
            logger.info(f"Loaded CSV file {file_path} into table {table_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load CSV file {file_path}: {e}")
            return False
    
    def _normalize_column_name(self, column: str) -> str:
        """Normalize column name for consistent access"""
        if not is_feature_enabled('ENABLE_CSV_NORMALIZATION'):
            return column
        
        # Convert to lowercase and replace spaces with underscores
        normalized = re.sub(r'\s+', '_', column.lower().strip())
        
        # Remove special characters except underscores
        normalized = re.sub(r'[^a-z0-9_]', '', normalized)
        
        # Ensure it starts with a letter
        if normalized and not normalized[0].isalpha():
            normalized = f"col_{normalized}"
        
        return normalized
    
    def _infer_data_types(self, df: pd.DataFrame) -> Dict[str, str]:
        """Infer data types for DataFrame columns"""
        data_types = {}
        
        for column in df.columns:
            # Sample non-null values
            sample_values = df[column].dropna().head(100)
            
            if len(sample_values) == 0:
                data_types[column] = "text"
                continue
            
            # Check for numeric types
            if pd.api.types.is_numeric_dtype(df[column]):
                if df[column].dtype == 'int64':
                    data_types[column] = "integer"
                elif df[column].dtype == 'float64':
                    data_types[column] = "float"
                else:
                    data_types[column] = "numeric"
            
            # Check for date types
            elif pd.api.types.is_datetime64_any_dtype(df[column]):
                data_types[column] = "date"
            
            # Check for boolean types
            elif pd.api.types.is_bool_dtype(df[column]):
                data_types[column] = "boolean"
            
            # Default to text
            else:
                data_types[column] = "text"
        
        return data_types
    
    def _store_schema(self, schema: TableSchema) -> None:
        """Store table schema in database"""
        if not self.connection:
            return
        
        try:
            self.connection.execute("""
                INSERT OR REPLACE INTO table_schemas 
                (table_name, columns, data_types, constraints, source_file, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                schema.table_name,
                json.dumps(schema.columns),
                json.dumps(schema.data_types),
                json.dumps(schema.constraints),
                schema.source_file,
                schema.last_updated.isoformat()
            ))
            self.connection.commit()
        except Exception as e:
            logger.error(f"Failed to store schema: {e}")
    
    def _store_table_data(self, table_name: str, df: pd.DataFrame) -> None:
        """Store table data in database"""
        if not self.connection:
            return
        
        try:
            # Clear existing data for this table
            self.connection.execute(
                "DELETE FROM table_data WHERE table_name = ?",
                (table_name,)
            )
            
            # Insert new data
            for index, row in df.iterrows():
                row_id = str(index)
                row_data = row.to_dict()
                
                # Normalize missing values
                for key, value in row_data.items():
                    if pd.isna(value):
                        row_data[key] = "N/A"
                    elif isinstance(value, (int, float)):
                        # Format numbers appropriately
                        if key.lower() in ['salary', 'amount', 'cost', 'price']:
                            row_data[key] = self._format_currency(value)
                        elif key.lower() in ['date', 'start_date', 'end_date', 'hire_date']:
                            row_data[key] = self._format_date(value)
                
                # Store row
                self.connection.execute("""
                    INSERT INTO table_data (table_name, row_id, data, chunk_id, metadata)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    table_name,
                    row_id,
                    json.dumps(row_data),
                    None,  # chunk_id
                    json.dumps({})  # metadata
                ))
            
            self.connection.commit()
            logger.info(f"Stored {len(df)} rows for table {table_name}")
            
        except Exception as e:
            logger.error(f"Failed to store table data: {e}")
    
    def _format_currency(self, value: Union[int, float]) -> str:
        """Format numeric value as currency"""
        if not is_feature_enabled('ENABLE_CSV_NORMALIZATION'):
            return str(value)
        
        try:
            if pd.isna(value):
                return "N/A"
            
            # Format as USD with 2 decimal places and thousands separators
            formatted = "${:,.2f}".format(float(value))
            return formatted
        except (ValueError, TypeError):
            return str(value)
    
    def _format_date(self, value: Any) -> str:
        """Format date value consistently"""
        if not is_feature_enabled('ENABLE_CSV_NORMALIZATION'):
            return str(value)
        
        try:
            if pd.isna(value):
                return "N/A"
            
            # Convert to datetime if it's a string
            if isinstance(value, str):
                # Try common date formats
                for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S']:
                    try:
                        dt = pd.to_datetime(value, format=fmt)
                        break
                    except ValueError:
                        continue
                else:
                    # If no format matches, try pandas default parsing
                    dt = pd.to_datetime(value)
            else:
                dt = pd.to_datetime(value)
            
            # Format as ISO date
            return dt.strftime('%Y-%m-%d')
            
        except (ValueError, TypeError):
            return str(value)
    
    def find_employee_by_id(self, employee_id: str, table_name: Optional[str] = None) -> Optional[TableRow]:
        """Find employee record by ID"""
        if not is_feature_enabled('ENABLE_TABLE_RETRIEVER'):
            return None
        
        # Try to find in HR-related tables
        if not table_name:
            table_name = self._find_hr_table()
        
        if not table_name:
            return None
        
        try:
            cursor = self.connection.execute("""
                SELECT * FROM table_data 
                WHERE table_name = ? AND json_extract(data, '$.employee_id') = ?
            """, (table_name, employee_id))
            
            row = cursor.fetchone()
            if row:
                return TableRow(
                    row_id=row['row_id'],
                    data=json.loads(row['data']),
                    source_file=row['source_file'],
                    chunk_id=row['chunk_id'],
                    metadata=json.loads(row['metadata']) if row['metadata'] else {}
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to find employee by ID: {e}")
            return None
    
    def find_employee_by_email(self, email: str, table_name: Optional[str] = None) -> Optional[TableRow]:
        """Find employee record by email"""
        if not is_feature_enabled('ENABLE_TABLE_RETRIEVER'):
            return None
        
        # Try to find in HR-related tables
        if not table_name:
            table_name = self._find_hr_table()
        
        if not table_name:
            return None
        
        try:
            cursor = self.connection.execute("""
                SELECT * FROM table_data 
                WHERE table_name = ? AND json_extract(data, '$.email') = ?
            """, (table_name, email))
            
            row = cursor.fetchone()
            if row:
                return TableRow(
                    row_id=row['row_id'],
                    data=json.loads(row['data']),
                    source_file=row['source_file'],
                    chunk_id=row['chunk_id'],
                    metadata=json.loads(row['metadata']) if row['metadata'] else {}
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to find employee by email: {e}")
            return None
    
    def find_employee_by_name(self, name: str, table_name: Optional[str] = None) -> List[TableRow]:
        """Find employee records by name (fuzzy matching)"""
        if not is_feature_enabled('ENABLE_TABLE_RETRIEVER'):
            return []
        
        # Try to find in HR-related tables
        if not table_name:
            table_name = self._find_hr_table()
        
        if not table_name:
            return []
        
        try:
            # Look for name in various name fields
            name_fields = ['name', 'full_name', 'first_name', 'last_name', 'employee_name']
            results = []
            
            for field in name_fields:
                cursor = self.connection.execute("""
                    SELECT * FROM table_data 
                    WHERE table_name = ? AND json_extract(data, ?) LIKE ?
                """, (table_name, f'$.{field}', f'%{name}%'))
                
                for row in cursor.fetchall():
                    table_row = TableRow(
                        row_id=row['row_id'],
                        data=json.loads(row['data']),
                        source_file=row['source_file'],
                        chunk_id=row['chunk_id'],
                        metadata=json.loads(row['metadata']) if row['metadata'] else {}
                    )
                    results.append(table_row)
            
            # Remove duplicates based on row_id
            seen = set()
            unique_results = []
            for result in results:
                if result.row_id not in seen:
                    seen.add(result.row_id)
                    unique_results.append(result)
            
            return unique_results
            
        except Exception as e:
            logger.error(f"Failed to find employee by name: {e}")
            return []
    
    def _find_hr_table(self) -> Optional[str]:
        """Find the HR table name"""
        hr_keywords = ['hr', 'employee', 'staff', 'personnel', 'human_resources']
        
        for table_name in self.tables.keys():
            if any(keyword in table_name.lower() for keyword in hr_keywords):
                return table_name
        
        return None
    
    def get_table_schema(self, table_name: str) -> Optional[TableSchema]:
        """Get schema for a specific table"""
        return self.tables.get(table_name)
    
    def get_all_tables(self) -> List[str]:
        """Get list of all table names"""
        return list(self.tables.keys())
    
    def query_table(
        self, 
        table_name: str, 
        conditions: Dict[str, Any],
        limit: Optional[int] = None
    ) -> List[TableRow]:
        """Query table with specific conditions"""
        if not is_feature_enabled('ENABLE_TABLE_RETRIEVER'):
            return []
        
        if not self.connection or table_name not in self.tables:
            return []
        
        try:
            # Build WHERE clause
            where_clauses = []
            params = [table_name]
            
            for field, value in conditions.items():
                where_clauses.append(f"json_extract(data, '$.{field}') = ?")
                params.append(value)
            
            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            
            # Build query
            query = f"""
                SELECT * FROM table_data 
                WHERE table_name = ? AND {where_sql}
            """
            
            if limit:
                query += f" LIMIT {limit}"
            
            cursor = self.connection.execute(query, params)
            results = []
            
            for row in cursor.fetchall():
                table_row = TableRow(
                    row_id=row['row_id'],
                    data=json.loads(row['data']),
                    source_file=row['source_file'],
                    chunk_id=row['chunk_id'],
                    metadata=json.loads(row['metadata']) if row['metadata'] else {}
                )
                results.append(table_row)
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to query table: {e}")
            return []
    
    def export_table_to_csv(self, table_name: str, output_path: str) -> bool:
        """Export table data to CSV file"""
        if not is_feature_enabled('ENABLE_TABLE_RETRIEVER'):
            return False
        
        if table_name not in self.tables:
            logger.error(f"Table {table_name} not found")
            return False
        
        try:
            cursor = self.connection.execute("""
                SELECT data FROM table_data WHERE table_name = ?
            """, (table_name,))
            
            rows = []
            for row in cursor.fetchall():
                data = json.loads(row['data'])
                rows.append(data)
            
            if rows:
                df = pd.DataFrame(rows)
                df.to_csv(output_path, index=False)
                logger.info(f"Exported table {table_name} to {output_path}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to export table: {e}")
            return False
    
    def close(self) -> None:
        """Close database connection"""
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.info("Database connection closed")

# Global table retriever instance
table_retriever = TableRetriever()

def get_table_retriever() -> TableRetriever:
    """Get the global table retriever instance"""
    return table_retriever
