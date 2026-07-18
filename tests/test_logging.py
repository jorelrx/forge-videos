from forge.logging import setup_logging, get_logger

def test_setup_idempotent_and_logger_usable():
    setup_logging("INFO")
    setup_logging("INFO")  # segunda chamada não quebra
    log = get_logger("test")
    log.info("ok", campo=1)  # não levanta
