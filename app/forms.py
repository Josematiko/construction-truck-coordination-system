from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, SelectField, IntegerField, TextAreaField
from wtforms.fields import DateField
from wtforms.validators import DataRequired, Length, Email, EqualTo, Regexp, Optional, ValidationError, NumberRange



class RegisterForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired(), Regexp(r'^[a-zA-Z\s]+$', message='First name must contain only letters and spaces.')])
    middle_name = StringField('Middle Name', validators=[Optional(), Regexp(r'^[a-zA-Z\s]*$', message='Middle name must contain only letters and spaces.')])
    last_name = StringField('Last Name', validators=[DataRequired(), Regexp(r'^[a-zA-Z\s]+$', message='Last name must contain only letters and spaces.')])
    email = StringField('Email', validators=[DataRequired(), Email()])
    phone = StringField('Phone Number', validators=[DataRequired(), Regexp(r'^\+?\d{1,12}$', message='Phone number must contain only digits and an optional leading +, with a maximum of 12 digits.')])

    password = PasswordField('Password', validators=[DataRequired(), Length(min=6, max=9)])
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('password')]
    )

    role = SelectField(
        'Register as',
        choices=[
            ('', 'Select role...'),
            ('customer', 'Customer'),
            ('driver', 'Driver'),
            ('owner', 'Truck Owner')
        ],
        validators=[DataRequired()]
    )

    # Driver-specific fields
    license_number = StringField('License Number')
    license_photo = FileField('License Photo', validators=[FileAllowed(['jpg', 'png', 'jpeg'], 'Images only!')])

    submit = SubmitField('Register')


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=6, max=12)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('new_password')])
    submit = SubmitField('Change Password')


class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send Reset Link')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=6, max=9)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')


class RatingForm(FlaskForm):
    rating = SelectField('Rating', choices=[(1, '1 Star'), (2, '2 Stars'), (3, '3 Stars'), (4, '4 Stars'), (5, '5 Stars')], coerce=int, validators=[DataRequired()])
    comment = TextAreaField('Comment (optional)')
    submit = SubmitField('Submit Rating')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')
    
    
class MaterialForm(FlaskForm):
    name = StringField('Material Name', validators=[DataRequired()])
    price = StringField('Price', validators=[DataRequired()])
    discount_price = StringField('Discount Price (optional)', validators=[Optional()])
    discount_start = DateField('Discount Start (optional)', format='%Y-%m-%d', validators=[Optional()], render_kw={'type': 'date'})
    discount_end = DateField('Discount End (optional)', format='%Y-%m-%d', validators=[Optional()], render_kw={'type': 'date'})
    submit = SubmitField('Save Material')


class LocationForm(FlaskForm):
    name = StringField('Drop Area Name', validators=[DataRequired()])
    submit = SubmitField('Save Drop Area')


class OrderForm(FlaskForm):
    material = SelectField(
        'Material',
        coerce=int,
        validators=[DataRequired(message="Please select a material")]
    )

    quantity = IntegerField(
        'Quantity (trucks)',
        validators=[
            DataRequired(),
            NumberRange(min=1, message="Quantity must be at least 1")
        ]
    )

    drop_area = SelectField(
        'Drop Area',
        coerce=int,
        validators=[DataRequired(message="Please select a drop location")]
    )

    payment_method = SelectField(
        'Payment Method',
        choices=[('M-Pesa', 'M-Pesa'), ('Paybill', 'Paybill')],
        validators=[DataRequired(message="Please select a payment method")]
    )

    phone_number = StringField(
        'M-Pesa Phone Number',
        validators=[
            Optional(),
            Regexp(
                r'^\+?\d{9,12}$',
                message='Enter a valid phone number e.g. 07XXXXXXXX or 2547XXXXXXXX.'
            )
        ]
    )

    def validate_phone_number(self, field):
        phone = (field.data or '').strip()
        if self.payment_method.data == 'M-Pesa' and not phone:
            raise ValidationError("M-Pesa phone number is required.")

    submit = SubmitField('Place Order')


class TruckForm(FlaskForm):
    registration_number = StringField('Registration Number', validators=[DataRequired()])
    submit = SubmitField('Add Truck')


class PaymentForm(FlaskForm):
    payment_method = SelectField(
        'Payment Method',
        choices=[('M-Pesa', 'M-Pesa'), ('Paybill', 'Paybill')],
        validators=[DataRequired()]
    )
    phone_number = StringField(
        'M-Pesa Phone Number',
        validators=[
            Optional(),
            Regexp(r'^\+?\d{9,12}$', message='Enter a valid phone number e.g. 07XXXXXXXX or 2547XXXXXXXX.')
        ]
    )

    def validate_phone_number(self, field):
        phone = (field.data or '').strip()
        if self.payment_method.data == 'M-Pesa' and not phone:
            raise ValidationError("M-Pesa phone number is required.")

    submit = SubmitField('Pay Now')


class PaymentSettingsForm(FlaskForm):
    paybill_number = StringField(
        'Paybill Number',
        validators=[
            Optional(),
            Regexp(r'^\d{5,12}$', message='Paybill number must be digits only (5-12 digits).')
        ]
    )
    submit = SubmitField('Save Paybill')


class ManualPaymentConfirmationForm(FlaskForm):
    provider_reference = StringField(
        'Payment Reference',
        validators=[Optional(), Length(max=120)]
    )
    status_message = TextAreaField(
        'Admin Note',
        validators=[Optional(), Length(max=255)]
    )
    submit = SubmitField('Confirm Payment')


class ChatForm(FlaskForm):
    message = TextAreaField('Message', validators=[DataRequired()])
    submit = SubmitField('Send')


class DriverResponseForm(FlaskForm):
    response = SelectField(
        'Response',
        choices=[('accept', 'Accept'), ('decline', 'Decline')],
        validators=[DataRequired()]
    )
    reason = TextAreaField('Reason (if declining)')
    submit = SubmitField('Submit Response')


class TruckStatusForm(FlaskForm):
    status = SelectField(
        'Truck Status',
        choices=[('good', 'Good'), ('need_service', 'Need Service'), ('bad', 'Bad')],
        validators=[DataRequired()]
    )
    submit = SubmitField('Update Status')
    
    
               
