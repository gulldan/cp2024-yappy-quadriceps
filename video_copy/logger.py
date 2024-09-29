import logging

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

c_handler = logging.StreamHandler()

c_format = logging.Formatter("%(name)s - %(levelname)s - %(message)s")
c_handler.setFormatter(c_format)

logger.addHandler(c_handler)
