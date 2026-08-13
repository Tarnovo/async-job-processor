import csv
import random

def generate_huge_csv(filename="stress_test_10k.csv", num_rows=10000):
    # Columns expected by our employee_processor
    fieldnames = ["name", "age", "email", "department"]
    departments = ["Engineering", "HR", "Marketing", "Sales", "Finance"]
    
    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        
        for i in range(num_rows):
            # Intentionally sprinkling "invalid" rows every 100 iterations 
            # to test the error handling and result generation logic in S3
            if i % 100 == 0:
                age = random.choice([-5, "invalid_age", 150])
            else:
                age = random.randint(18, 65)
                
            writer.writerow({
                "name": f"Employee_{i}",
                "age": age,
                "email": f"employee_{i}@shadowcompany.com",
                "department": random.choice(departments)
            })
    print(f"Huge test file successfully generated: {filename} ({num_rows} rows)")

if __name__ == "__main__":
    generate_huge_csv()