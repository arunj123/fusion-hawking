import ast
from .models import Service, Method, Struct, Field, Type

class AbstractParser:
    def parse(self, filepath: str) -> tuple[list[Struct], list[Service]]:
        raise NotImplementedError

class PythonASTParser(AbstractParser):
    def parse(self, filepath: str) -> tuple[list[Struct], list[Service]]:
        with open(filepath, "r") as f:
            tree = ast.parse(f.read())
            
        structs = []
        services = []
        
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if self._is_dataclass(node):
                    structs.append(self._parse_struct(node))
                
                service_id = self._get_decorator_id(node, 'service')
                if service_id is not None:
                    services.append(self._parse_service(node, service_id))
                    
        return structs, services

    def _is_dataclass(self, node: ast.ClassDef) -> bool:
        for d in node.decorator_list:
            if isinstance(d, ast.Name) and d.id == 'dataclass':
                return True
            if isinstance(d, ast.Attribute) and d.attr == 'dataclass':
                return True
        return False

    def _get_decorator_id(self, node, name: str) -> int | None:
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == name:
                for kw in d.keywords:
                    if kw.arg == 'id':
                        return kw.value.value
        return None

    def _parse_type(self, annotation) -> Type:
        if isinstance(annotation, ast.Name):
            return Type(annotation.id)
        elif isinstance(annotation, ast.Subscript):
             if isinstance(annotation.value, ast.Name) and annotation.value.id == 'List':
                 inner = self._parse_type(annotation.slice)
                 return Type(inner.name, is_list=True)
        elif isinstance(annotation, ast.Constant) and annotation.value is None:
             return Type("None")
        return Type("Unknown")

    def _parse_struct(self, node: ast.ClassDef) -> Struct:
        fields = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign):
                name = item.target.id
                field_type = self._parse_type(item.annotation)
                fields.append(Field(name, field_type))
        return Struct(node.name, fields)

    def _parse_service(self, node: ast.ClassDef, service_id: int) -> Service:
        methods = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_id = self._get_decorator_id(item, 'method')
                if method_id is not None:
                     args = []
                     for arg in item.args.args:
                         if arg.arg == 'self': continue
                         if arg.annotation:
                             args.append(Field(arg.arg, self._parse_type(arg.annotation)))
                     
                     ret_type = Type("None")
                     if item.returns:
                         ret_type = self._parse_type(item.returns)
                         
                     methods.append(Method(item.name, method_id, args, ret_type))
        return Service(node.name, service_id, methods)
