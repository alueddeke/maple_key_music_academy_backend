from django.db import models

# Create your models here.
class Teacher(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=255)
    address = models.CharField(max_length=225)
    phoneNumber = models.CharField(max_length=11)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name


class Student(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE) #cascade = delete all students when teacher is deleted
    name = models.CharField( max_length=225)
    email = models.EmailField(max_length=255)
    address = models.CharField(max_length=225)
    phoneNumber = models.CharField(max_length=11)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name



class Lesson(models.Model):
    rate = models.DecimalField(max_digits=6, decimal_places=2, default=80.00)
    date = models.DateTimeField()
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    duration = models.DecimalField(max_digits=4, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def total_cost(self):
        return self.rate * self.duration
    
    def __str__(self):
        return f"{self.student.name} - {self.date}"

class Invoice(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('paid', 'Paid'), ('overdue', 'Overdue')]
    lessons = models.ManyToManyField(Lesson)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    paymentBalance = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=255, choices=STATUS_CHOICES, default='pending')
    date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def calculate_payment_balance(self):
        """Calculate the total payment balance by summing all lesson costs"""
        total = 0
        for lesson in self.lessons.all():
            total += lesson.total_cost()
        return total
    
    def save(self, *args, **kwargs):
        """
        Override the save method to calculate the payment balance - makes sure payment balance is updated when invoice is saved
        """
        # Calculate the total from all lessons and set it as payment balance
        self.paymentBalance = self.calculate_payment_balance()
        # Call the parent save method to actually save to database
        super().save(*args, **kwargs)
    

    
    def __str__(self):
        return f"{self.teacher.name} - {self.date} - {self.paymentBalance}"


    





