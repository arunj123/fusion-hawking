from ..models import Struct, Service

class AbstractGenerator:
    def generate(self, structs: list[Struct], services: list[Service]) -> dict[str, str]:
        raise NotImplementedError
