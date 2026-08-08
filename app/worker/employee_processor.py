from typing import BinaryIO
import io
import csv
from app.core.exceptions import (
    MissingHeadersError, 
    InvalidCSVError
)
from app.core.models import (
    CSVProcessingResponse,
    CSVSummary,
    InvalidRow
)

# Validates a single row of the CSV file.
def validate(row: dict[str, str]) -> str:
    try:
        name = row["name"]
        department = row["department"]
        age = int(row["age"])
        
        if not name.strip():
            return "name is empty"
        
        if not department.strip():
            return "department is empty"
        
        if age < 0 or age > 120:
            return "age must be between 0 and 120"
        
        if age < 18:
            return "underage"
        
        return "valid"

    except ValueError:
        return "invalid_value"


# Processes the CSV file and returns a summary of valid, underage, and invalid rows.
def process_csv(file: BinaryIO) -> CSVProcessingResponse:
    text_file = io.TextIOWrapper(file, encoding="utf-8")
    reader = csv.DictReader(text_file)
    if reader.fieldnames is None:
        raise MissingHeadersError("CSV file is empty or missing headers. Make sure the file contains a header.")
    
    # Check if the required headers are present in the uploaded CSV file
    required_headers = {"name", "age", "department"}
    uploaded_headers = set(reader.fieldnames)
    if not required_headers.issubset(uploaded_headers):
        raise InvalidCSVError("Your headers are incorrect. Your .csv file must contain these headers: 'name', 'age', 'department'")
    
   
    valid = 0
    underage = 0
    invalid_value = 0
    invalid_rows: list[InvalidRow] = []
 
    # Process each row in the CSV file and validate it
    for row in reader:
        result = validate(row)
        if result == "valid":
            valid += 1
        elif result == "underage":
            underage += 1
        else:
            invalid_value += 1
            invalid_rows.append(
                InvalidRow(
                    row_number=reader.line_num,
                    reason=result
                )
            )

  
    return CSVProcessingResponse(
        summary=CSVSummary(
            valid=valid,
            underage=underage,
            invalid_value=invalid_value
        ),
        invalid_rows=invalid_rows
    )
