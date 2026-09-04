from app.services.email_sender import send_email


def main():
    result = send_email(
        to_email="delivered@resend.dev",
        subject="Autonomous SDR Agent - Delivery Test",
        body=(
            "Hello,\n\n"
            "This is a controlled delivery test from the "
            "Autonomous SDR Agent.\n\n"
            "Regards,\n"
            "Saurabh Shinde"
        ),
        allow_test_recipient=True,
    )

    print("\nResend response:")
    print("----------------")
    print(result)


if __name__ == "__main__":
    main()
