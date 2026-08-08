import csv
import random

def generate_huge_csv(filename="stress_test_10k.csv", num_rows=10000):
    # Bizim employee_processor'ın beklediği kolonlar
    fieldnames = ["name", "age", "email", "department"]
    departments = ["Engineering", "HR", "Marketing", "Sales", "Finance"]
    
    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        
        for i in range(num_rows):
            # Arada bilerek "hatalı/invalid" satırlar serpiştiriyoruz ki S3'e sonuçları yazma mantığı da test edilsin
            # Her 100 satırda bir yaşı eksi veya geçersiz yapalım
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
    print(f"🔥 Devasa test dosyası başarıyla üretildi: {filename} ({num_rows} satır)")

if __name__ == "__main__":
    generate_huge_csv()