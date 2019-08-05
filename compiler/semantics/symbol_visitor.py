from chemicals.chemtypes import ChemTypeResolver, ChemTypes
from chemicals.identifier import Identifier
from compiler.data_structures.function import Function
from compiler.data_structures.variable import Symbol
from grammar.parsers.python.BSParser import BSParser
from shared.bs_exceptions import UndefinedVariable, UndefinedFunction, UnsupportedOperation
from .bs_base_visitor import BSBaseVisitor


class SymbolTableVisitor(BSBaseVisitor):

    def __init__(self, symbol_table, identifier: Identifier):
        super().__init__(symbol_table, "SimpleSymbolVisitor", identifier)

    def visitProgram(self, ctx: BSParser.ProgramContext):
        # Visiting globals is done in global_visitor.
        # Add main first, it is the root.
        self.symbol_table.new_scope("main")
        self.scope_stack.append('main')

        if ctx.functions():
            self.visitFunctions(ctx.functions())

        # We set current_scope equal to main for because the statements
        # hereafter are main's statements.
        self.symbol_table.current_scope = self.symbol_table.scope_map['main']
        for statement in ctx.statements():
            self.visitStatements(statement)

    def visitFunctions(self, ctx: BSParser.FunctionsContext):
        for func in ctx.functionDeclaration():
            self.visitFunctionDeclaration(func)

    def visitFunctionDeclaration(self, ctx: BSParser.FunctionDeclarationContext):
        """
        This populates the symbol table with methods.
        It cannot handle return values.  So all records
        In the symbol table will be empty typed.
        :param ctx: visitor context
        :return: nothing
        """
        name = ctx.IDENTIFIER().__str__()

        self.symbol_table.new_scope(name)

        args = list()
        if ctx.formalParameters():
            args = self.visitFormalParameters(ctx.formalParameters())

        for statement in ctx.statements():
            self.visitStatements(statement)

        types = set()
        if ctx.functionTyping():
            types.update(self.visitFunctionTyping(ctx.functionTyping()))
        types.update(self.visitReturnStatement(ctx.returnStatement()))

        bs_function = Function(name, types, args)

        self.symbol_table.functions[name] = bs_function
        self.symbol_table.end_scope()

    def visitReturnStatement(self, ctx: BSParser.ReturnStatementContext):
        # It's either a primary or a method call
        types = set()
        if ctx.primary():
            var = self.visitPrimary(ctx.primary())
            local = self.symbol_table.get_local(var['name'])
            # If we don't have a local, this is a constant.
            if local:
                types = self.symbol_table.get_local(var['name']).types
            else:
                types = ChemTypeResolver.numbers()
        elif ctx.methodCall():
            raise UnsupportedOperation("You need to fix the grammar, a method call is currently: vd ID LP (el)? RP")
        else:
            raise UnsupportedOperation("Only method calls or values are returnable.")

        return types

    def visitFormalParameters(self, ctx: BSParser.FormalParametersContext):
        if ctx.formalParameterList():
            return self.visitFormalParameterList(ctx.formalParameterList())
        else:
            return list()

    def visitFormalParameterList(self, ctx: BSParser.FormalParameterListContext):
        params = list()
        for param in ctx.formalParameter():
            params.append(self.visitFormalParameter(param))
        return params

    def visitFormalParameter(self, ctx: BSParser.FormalParameterContext):
        if ctx.unionType():
            types = self.visitUnionType(ctx.unionType())
        else:
            types = {ChemTypes.UNKNOWN}
        var = ctx.IDENTIFIER().__str__()
        symbol = Symbol(var, self.scope_stack[-1], types)
        self.symbol_table.add_local(symbol)
        return symbol

    def visitHeat(self, ctx: BSParser.HeatContext):
        name = self.visitVariable(ctx.variable())['name']
        use = self.symbol_table.get_local(name)
        if not use:
            raise UndefinedVariable("{} is not defined.".format(name))
        if not ChemTypeResolver.is_mat_in_set(use.types):
            use.types.add(ChemTypes.MAT)
            self.symbol_table.update_symbol(use)
        return None

    def visitDispose(self, ctx: BSParser.DisposeContext):
        name = self.visitVariable(ctx.variable())['name']
        use = self.symbol_table.get_local(name)
        if not use:
            raise UndefinedVariable("{} is not defined.".format(name))
        if not ChemTypeResolver.is_mat_in_set(use.types):
            use.types.add(ChemTypes.MAT)
            self.symbol_table.update_symbol(use)
        return None

    def visitMix(self, ctx: BSParser.MixContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())

        symbol = Symbol(deff['name'], self.scope_stack[-1], self.resolve_types(deff))
        # Look through the RHS vars.
        for fluid in ctx.variable():
            temp = self.visitVariable(fluid)
            var = self.symbol_table.get_local(temp['name'])
            if not var:
                raise UndefinedVariable("{} is not defined.".format(temp['name']))
            if not ChemTypeResolver.is_mat_in_set(var.types):
                # This is the best we can do at this point.
                # We won't be able to further classify anything
                # further because if the identifier hasn't
                # figured anything out by now, it won't.
                var.types.update(self.resolve_types({'name': var.name, 'types': var.types}))
            # Update the RHS types.
            self.symbol_table.update_symbol(var)
            # Union the types of the RHS with the LHS
            symbol.types.update(var.types)
        # Add the symbol to the table.
        self.symbol_table.add_local(symbol)
        return None

    def visitDetect(self, ctx: BSParser.DetectContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())
        self.symbol_table.add_local(Symbol(deff['name'], self.scope_stack[-1], ChemTypeResolver.numbers()))
        use = self.visitVariable(ctx.variable())
        var = self.symbol_table.get_local(use['name'])
        if not var:
            raise UndefinedVariable("{} is not defined.".format(use['name']))
        module = self.symbol_table.get_global(ctx.IDENTIFIER().__str__())
        if not module:
            raise UndefinedVariable("{} isn't declared in the manifest.".format(ctx.IDENTIFIER().__str__()))
        if ChemTypes.MODULE not in module.types:
            raise UndefinedVariable("There is no module named {} declared in the manifest.".format(module.name))
        if not ChemTypeResolver.is_mat_in_set(var.types):
            var.types.add(ChemTypes.MAT)
            self.symbol_table.update_symbol(var)
        return None

    def visitSplit(self, ctx: BSParser.SplitContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())
        use = self.visitVariable(ctx.variable())
        if not self.symbol_table.get_local(use['name']):
            raise UndefinedVariable("{} is not defined.".format(use['name']))
        if not ChemTypeResolver.is_mat_in_set(deff['types']):
            deff['types'].update(self.identifier.identify(deff['name'], deff['types']))
        deff['types'].update(self.symbol_table.get_local(use['name']).types)
        self.symbol_table.add_local(Symbol(deff['name'], self.scope_stack[-1], deff['types']))
        return None

    def visitDispense(self, ctx: BSParser.DispenseContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())
        self.symbol_table.add_local(Symbol(deff['name'], self.scope_stack[-1], self.resolve_types(deff)))
        if not self.symbol_table.get_global(ctx.IDENTIFIER().__str__()):
            raise UndefinedVariable("{} isn't declared in the manifest.".format(ctx.IDENTIFIER().__str__()))
        return None

    def visitGradient(self, ctx: BSParser.GradientContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())
        symbol = Symbol(deff['name'], self.scope_stack[-1], self.resolve_types(deff))
        for use in ctx.IDENTIFIER():
            var = self.symbol_table.get_symbol(use.__str__())
            if not ChemTypeResolver.is_mat_in_set(var.types):
                var.types.add(ChemTypes.MAT)
            self.symbol_table.update_symbol(var)
            symbol.types.update(var.types)
        self.symbol_table.add_local(symbol)

        return None

    def visitStore(self, ctx: BSParser.StoreContext):
        use = self.visitVariable(ctx.variable())
        symbol = self.symbol_table.get_local(use['name'])
        if not symbol:
            raise UndefinedVariable("{} is not defined.".format(use['name']))
        if not ChemTypeResolver.is_mat_in_set(symbol.types):
            symbol.types.add(ChemTypes.MAT)
            self.symbol_table.update_symbol(symbol)
        return None

    def visitMath(self, ctx: BSParser.MathContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())
        symbol = Symbol(deff['name'], self.scope_stack[-1], ChemTypeResolver.numbers())

        for use in ctx.primary():
            var = self.visitPrimary(use)
            if not ChemTypeResolver.is_number_in_set(var['types']):
                local = self.symbol_table.get_local(var['name'])
                if not local:
                    raise UndefinedVariable("{} is not defined.".format(var['name']))
                local.types.update(ChemTypeResolver.numbers())
                if ChemTypes.UNKNOWN in local.types:
                    local.types.remove(ChemTypes.UNKNOWN)
                self.symbol_table.update_symbol(local)

        self.symbol_table.add_local(symbol)

        return None

    def visitMethodCall(self, ctx: BSParser.MethodCallContext):
        # First see if this method exists.
        method_name = ctx.IDENTIFIER().__str__()
        if method_name not in self.symbol_table.functions.keys():
            raise UndefinedFunction("No function {} defined.".format(method_name))

        deff = self.visitVariableDefinition(ctx.variableDefinition())

        args = list()
        if ctx.expressionList():
            args = self.visitExpressionList(ctx.expressionList())

        if len(args) != len(self.symbol_table.functions[method_name].args):
            raise UnsupportedOperation("Function {} takes {} arguments; {} arguments provided.".format(
                method_name, len(self.symbol_table.functions[method_name].args), len(args)))

        symbol = Symbol(deff['name'], self.scope_stack[-1], self.symbol_table.functions[method_name].types)

        self.symbol_table.add_local(symbol)
        return None

    def visitExpressionList(self, ctx: BSParser.ExpressionListContext):
        args = list()
        for primary in ctx.primary():
            args.append(self.visitPrimary(primary))
        return args
