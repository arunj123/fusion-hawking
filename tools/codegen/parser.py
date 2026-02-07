import ast
from typing import Optional
from .models import Service, Method, Struct, Field, Type, Event, FieldSpec

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
                    major = self._get_decorator_id(node, 'service', 'major_version') or 1
                    minor = self._get_decorator_id(node, 'service', 'minor_version') or 0
                    services.append(self._parse_service(node, service_id, major, minor))
                    
        return structs, services

    def _is_dataclass(self, node: ast.ClassDef) -> bool:
        for d in node.decorator_list:
            if isinstance(d, ast.Name) and d.id == 'dataclass':
                return True
            if isinstance(d, ast.Attribute) and d.attr == 'dataclass':
                return True
        return False

    def _get_decorator_id(self, node, name: str, key: str = 'id') -> Optional[int]:
        return self._get_decorator_id(node, name, key)

    def _parse_type(self, annotation) -> Type:
        if isinstance(annotation, ast.Name):
            name = annotation.id
            # Map common IDL aliases if needed
            mapping = {
                'int': 'int',
                'float': 'float32',
                'str': 'string',
                'bool': 'bool'
            }
            return Type(mapping.get(name, name))
        elif isinstance(annotation, ast.Subscript):
             if isinstance(annotation.value, ast.Name) and annotation.value.id == 'List':
                 inner = self._parse_type(annotation.slice)
                 return Type("list", inner=inner)
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

    def _parse_service(self, node: ast.ClassDef, service_id: int, major: int = 1, minor: int = 0) -> Service:
        methods = []
        events = []
        fields = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                # Check for @method
                method_id = self._get_decorator_id(item, 'method', 'id')
                if method_id is not None:
                     methods.append(self._parse_method(item, method_id))
                
                event_id = self._get_decorator_id(item, 'event', 'id')
                if event_id is not None:
                     events.append(self._parse_event(item, event_id))
                     
                field_id = self._get_decorator_id(item, 'field', 'id')
                if field_id is not None:
                     fields.append(self._parse_field_method(item, field_id))
            
            elif isinstance(item, ast.AnnAssign):
                # Check for @field
                field_id = self._get_decorator_id(item, 'field', 'id')
                if field_id is not None:
                    fields.append(self._parse_field_spec(item))
                    
        return Service(node.name, service_id, methods, events, fields, major, minor)

    def _parse_method(self, item: ast.FunctionDef, method_id: int) -> Method:
        args = []
        for arg in item.args.args:
            if arg.arg == 'self': continue
            if arg.annotation:
                args.append(Field(arg.arg, self._parse_type(arg.annotation)))
        
        ret_type = Type("None")
        if item.returns:
            ret_type = self._parse_type(item.returns)
            
        return Method(item.name, method_id, args, ret_type)

    def _parse_event(self, item: ast.FunctionDef, event_id: int) -> Event:
        # Events use function arguments as payload
        args = []
        for arg in item.args.args:
            if arg.arg == 'self': continue
            if arg.annotation:
                args.append(Field(arg.arg, self._parse_type(arg.annotation)))
        return Event(item.name, event_id, args)

    def _parse_field_method(self, item: ast.FunctionDef, field_id: int) -> FieldSpec:
        name = item.name
        # Type is the return type of the method
        field_type = Type("None")
        if item.returns:
            field_type = self._parse_type(item.returns)
            
        get_id = self._get_decorator_id(item, 'field', 'get_id')
        set_id = self._get_decorator_id(item, 'field', 'set_id')
        notifier_id = self._get_decorator_id(item, 'field', 'notifier_id')
        
        return FieldSpec(name, field_id, field_type, get_id, set_id, notifier_id)

    def _parse_field_spec(self, item: ast.AnnAssign) -> FieldSpec:
        name = item.target.id
        field_type = self._parse_type(item.annotation)
        
        # Get decorator details
        field_id = self._get_decorator_id(item, 'field', 'id')
        get_id = self._get_decorator_id(item, 'field', 'get_id')
        set_id = self._get_decorator_id(item, 'field', 'set_id')
        notifier_id = self._get_decorator_id(item, 'field', 'notifier_id')
        
        return FieldSpec(name, field_id, field_type, get_id, set_id, notifier_id)

    def _get_decorator_id(self, node, decorator_name: str, key: str = 'id') -> Optional[int]:
        if not hasattr(node, 'decorator_list'): return None
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == decorator_name:
                for kw in d.keywords:
                    # Parse 'id' or other keys
                    if kw.arg == key:
                         if isinstance(kw.value, ast.Constant):
                             return kw.value.value
                         # Handle unary minus for negative values if needed, mostly IDs are positive
                         if isinstance(kw.value, ast.UnaryOp) and isinstance(kw.value.op, ast.USub) and isinstance(kw.value.operand, ast.Constant):
                             return -kw.value.operand.value
        return None
