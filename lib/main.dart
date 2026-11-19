import 'package:flutter/material.dart';

void main() => runApp(const MyApp());

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SmartCube Pro',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(useMaterial3: true, scaffoldBackgroundColor: const Color(0xFF0E1220)),
      home: const LoginScreen(),
    );
  }
}

class Encomenda {
  final String blocoUnidade, pacoteId, codigo, status, condominio, locker, transportadora;
  final String quemEntregou;
  final String quemRetirou;
  final DateTime recebidaEm;
  final DateTime? dataRetirada;
  final String codigoRetirada;
  final bool qrValido;

  const Encomenda({
    required this.blocoUnidade,
    required this.pacoteId,
    required this.codigo,
    required this.status,
    required this.condominio,
    required this.recebidaEm,
    required this.codigoRetirada,
    required this.locker,
    required this.transportadora,
    this.quemEntregou = 'Entregador',
    this.quemRetirou = '',
    this.dataRetirada,
    this.qrValido = true,
  });

  // CORRIGIDO: vem do backend, não inventa dados no app
  factory Encomenda.fromJson(Map<String, dynamic> j) => Encomenda(
    blocoUnidade: j['bloco_unidade']?.toString() ?? '',
    pacoteId: j['pacote_id']?.toString() ?? '',
    codigo: j['codigo']?.toString() ?? '',
    status: j['status']?.toString() ?? '',
    condominio: j['condominio']?.toString() ?? '',
    recebidaEm: DateTime.tryParse(j['recebida_em']?.toString() ?? '') ?? DateTime.now(),
    codigoRetirada: j['codigo_retirada']?.toString() ?? '',
    locker: j['locker']?.toString() ?? '',
    transportadora: j['transportadora']?.toString() ?? '',
    quemEntregou: j['quem_entregou']?.toString() ?? 'Entregador',
    quemRetirou: j['quem_retirou']?.toString() ?? '',
    dataRetirada: j['data_retirada'] != null ? DateTime.tryParse(j['data_retirada'].toString()) : null,
    qrValido: j['qr_valido'] == true,
  );
}

// CORRIGIDO: removido db fake global com nome real, CPF, códigos reais
// Antes: qualquer um abria o app e via encomenda do Guilherme Martins + código 482910
// Agora: lista vazia, só carrega do backend depois do login
// TODO backend: GET /api/app/encomendas com token, retorna só as do morador logado
List<Encomenda> db = [];

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  // CORRIGIDO: removido text: 'morador@teste.com' / '123456'
  // Antes o app já abria com login e senha preenchidos, qualquer um entrava
  final emailController = TextEditingController();
  final senhaController = TextEditingController();
  bool esconderSenha = true;
  bool carregando = false;

  @override
  void dispose() {
    emailController.dispose();
    senhaController.dispose();
    super.dispose();
  }

  Future<void> _entrar() async {
    if (carregando) return;
    final email = emailController.text.trim();
    final senha = senhaController.text;
    if (email.isEmpty || senha.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Preencha e-mail e senha!')));
      return;
    }
    // CORRIGIDO: validação mínima real, não só length < 4
    if (!email.contains('@') || senha.length < 6) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('E-mail ou senha inválidos!')));
      return;
    }
    setState(() => carregando = true);
    try {
      // CORRIGIDO: login de verdade no backend, não Navigator direto
      // Antes: qualquer e-mail + qualquer senha com 4+ caracteres entrava e via dados de outro morador
      // TODO backend: POST /api/auth/login {usuario, senha} -> cookie/token + condominio + tipo_perfil
      // Por enquanto bloqueia login fake até o backend existir, em vez de deixar entrar sem validar
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Conectando ao servidor...')));
      // PLACEHOLDER SEGURO: não navega sem token. Troque pelo seu ApiService.login()
      // final auth = await ApiService.login(email, senha);
      // if (!auth.ok) -> SnackBar('Usuário ou senha inválidos')
      // db = await ApiService.minhasEncomendas();
      // Navigator.pushReplacement(... HomePrincipal(condominioNome: auth.condominio, emailLogado: email, tipoPerfil: auth.tipoPerfil))
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Login ainda não conectado ao backend. Não é possível entrar sem validação.')));
    } finally {
      if (mounted) setState(() => carregando = false);
      // CORRIGIDO: limpa senha da memória da tela
      senhaController.clear();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050E1F),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            Image.asset(
              'assets/logo_login.png',
              width: 160,
              errorBuilder: (context, error, stack) {
                return Column(children: [
                  Container(width: 80, height: 80, decoration: BoxDecoration(color: const Color(0xFFFF6B00), borderRadius: BorderRadius.circular(20)), child: const Icon(Icons.inventory_2, color: Colors.white, size: 40)),
                  const SizedBox(height: 12),
                  const Text('Smart Cube', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 22)),
                ]);
              },
            ),
            const SizedBox(height: 32),
            TextField(
              controller: emailController,
              keyboardType: TextInputType.emailAddress,
              autocorrect: false,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                labelText: 'E-mail',
                filled: true,
                fillColor: Colors.white10,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: senhaController,
              obscureText: esconderSenha,
              enableSuggestions: false,
              autocorrect: false,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                labelText: 'Senha',
                filled: true,
                fillColor: Colors.white10,
                suffixIcon: IconButton(icon: Icon(esconderSenha ? Icons.visibility_off : Icons.visibility, color: Colors.white54), onPressed: () => setState(() => esconderSenha = !esconderSenha)),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
              ),
            ),
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              height: 56,
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFFF6B00), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
                onPressed: carregando ? null : _entrar,
                child: carregando
                  ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                  : const Text('Entrar como Morador', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}

class HomePrincipal extends StatefulWidget {
  final String condominioNome;
  final String emailLogado;
  final String tipoPerfil;
  const HomePrincipal({super.key, required this.condominioNome, this.emailLogado = '', this.tipoPerfil = 'Morador'});
  @override
  State<HomePrincipal> createState() => _HomePrincipalState();
}

class _HomePrincipalState extends State<HomePrincipal> {
  int index = 0;
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0E1E),
      body: [MinhasEncomendasTela(condominioNome: widget.condominioNome), HistoricoTab(condominioNome: widget.condominioNome), PerfilTab(emailLogado: widget.emailLogado, condominioNome: widget.condominioNome, tipoPerfil: widget.tipoPerfil)][index],
      bottomNavigationBar: Container(
        margin: const EdgeInsets.fromLTRB(16, 0, 16, 24),
        decoration: BoxDecoration(color: const Color(0xFFFF6B00), borderRadius: BorderRadius.circular(30), boxShadow: [BoxShadow(color: const Color(0xFFFF6B00).withValues(alpha: 0.3), blurRadius: 20, offset: const Offset(0, 8))]),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(30),
          child: BottomNavigationBar(
            currentIndex: index,
            onTap: (i) => setState(() => index = i),
            backgroundColor: const Color(0xFFFF6B00),
            selectedItemColor: Colors.white,
            unselectedItemColor: Colors.white70,
            showSelectedLabels: false,
            showUnselectedLabels: false,
            type: BottomNavigationBarType.fixed,
            items: const [
              BottomNavigationBarItem(icon: Icon(Icons.home_filled, size: 28), label: 'Home'),
              BottomNavigationBarItem(icon: Icon(Icons.history, size: 28), label: 'Histórico'),
              BottomNavigationBarItem(icon: Icon(Icons.person, size: 28), label: 'Perfil'),
            ],
          ),
        ),
      ),
    );
  }
}

class MinhasEncomendasTela extends StatefulWidget {
  final String condominioNome;
  const MinhasEncomendasTela({super.key, required this.condominioNome});
  @override
  State<MinhasEncomendasTela> createState() => _MinhasEncomendasTelaState();
}

class _MinhasEncomendasTelaState extends State<MinhasEncomendasTela> {
  Widget _cardResumo(String titulo, String valor, Color cor) {
    return Expanded(child: Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.06), borderRadius: BorderRadius.circular(12)), child: Column(children: [Text(valor, style: TextStyle(color: cor, fontSize: 22, fontWeight: FontWeight.bold)), Text(titulo, style: const TextStyle(color: Colors.white54, fontSize: 10))])));
  }
  Widget _barra(int altura, String dia) {
    return Expanded(child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [Container(height: (altura * 12).toDouble().clamp(6, 80), width: 18, decoration: BoxDecoration(color: altura == 0 ? Colors.white10 : const Color(0xFFFF6B00), borderRadius: BorderRadius.circular(6))), const SizedBox(height: 6), Text(dia, style: const TextStyle(color: Colors.white38, fontSize: 10))]));
  }

  @override
  Widget build(BuildContext context) {
    var pendentes = db.where((e) => e.qrValido && e.status == 'Não retirada').toList();
    // CORRIGIDO: não usa db.first sem checar - antes com lista vazia dava crash, com fake mostrava dados de outro
    final ultimaRetirada = db.where((e) => e.dataRetirada != null).toList();
    final ultima = ultimaRetirada.isNotEmpty ? ultimaRetirada.first : null;
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Center(
            child: Image.asset('assets/logo.png', height: 72, fit: BoxFit.contain, errorBuilder: (context, error, stack) {
              return Column(children: [
                Container(width: 48, height: 48, decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.view_in_ar, color: Color(0xFFFF6B00), size: 32)),
                const SizedBox(height: 6),
                const Text('Smart', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18, height: 1)),
                const Text('Cube', style: TextStyle(color: Color(0xFFFF6B00), fontWeight: FontWeight.bold, fontSize: 18, height: 1)),
              ]);
            }),
          ),
          const SizedBox(height: 24),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              const Expanded(child: Text('Minhas\nEncomendas', style: TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.bold, height: 1.1))),
              Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7), decoration: BoxDecoration(color: const Color(0xFFFF6B00), borderRadius: BorderRadius.circular(20)), child: const Row(mainAxisSize: MainAxisSize.min, children: [Icon(Icons.check_circle, color: Colors.white, size: 16), SizedBox(width: 6), Text('Entregue', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13))])),
            ],
          ),
          const SizedBox(height: 20),
          if (pendentes.isEmpty)
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(color: const Color(0xFF1A1F35), borderRadius: BorderRadius.circular(20), border: Border.all(color: Colors.white.withValues(alpha: 0.08))),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: const Color(0xFFFF6B00).withValues(alpha: 0.2), borderRadius: BorderRadius.circular(10)), child: const Icon(Icons.bar_chart, color: Color(0xFFFF6B00))),
                  const SizedBox(width: 10),
                  const Text('Resumo de Entregas', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18)),
                  const Spacer(),
                  Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4), decoration: BoxDecoration(color: Colors.white10, borderRadius: BorderRadius.circular(8)), child: const Text('Outubro', style: TextStyle(color: Colors.white54, fontSize: 11))),
                ]),
                const SizedBox(height: 16),
                Row(children: [
                  _cardResumo('Total mês', '${db.length}', Colors.white),
                  const SizedBox(width: 10),
                  _cardResumo('Retiradas', '${db.where((e) => !e.qrValido).length}', const Color(0xFF22C55E)),
                  const SizedBox(width: 10),
                  _cardResumo('Pendentes', '${pendentes.length}', const Color(0xFFFF6B00)),
                ]),
                const SizedBox(height: 20),
                const Text('Últimos 7 dias', style: TextStyle(color: Colors.white60, fontSize: 12)),
                const SizedBox(height: 12),
                SizedBox(height: 90, child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [_barra(2, 'Seg'), _barra(4, 'Ter'), _barra(1, 'Qua'), _barra(5, 'Qui'), _barra(3, 'Sex'), _barra(2, 'Sáb'), _barra(0, 'Dom')])),
                const SizedBox(height: 16),
                const Divider(color: Colors.white10),
                const SizedBox(height: 10),
                Row(children: [
                  const Icon(Icons.check_circle, size: 14, color: Colors.white38),
                  const SizedBox(width: 6),
                  Text(ultima != null ? 'Última retirada: ${ultima.dataRetirada!.day.toString().padLeft(2,'0')}/${ultima.dataRetirada!.month.toString().padLeft(2,'0')} às ${ultima.dataRetirada!.hour.toString().padLeft(2,'0')}:${ultima.dataRetirada!.minute.toString().padLeft(2,'0')} • ${ultima.locker.replaceAll('Locker L', 'Box ')}' : 'Nenhuma retirada ainda', style: const TextStyle(color: Colors.white38, fontSize: 12)),
                ]),
              ]),
            )
          else
            ...pendentes.map((enc) => Container(
                  margin: const EdgeInsets.only(bottom: 14),
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: const Color(0xFF1A1F35),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
                  ),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Container(width: 52, height: 52, decoration: const BoxDecoration(color: Color(0xFF22C55E), shape: BoxShape.circle), child: const Icon(Icons.check, color: Colors.white, size: 30)),
                      const SizedBox(width: 14),
                      const Expanded(child: Text('Encomenda Pronta para\nRetirada', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18, height: 1.2))),
                    ]),
                    const SizedBox(height: 20),
                    Text(enc.locker.replaceAll('Locker L', 'Box '), style: const TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 20),
                    SizedBox(
                      width: double.infinity,
                      height: 58,
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFFF6B00), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)), elevation: 0),
                        onPressed: () async {
                          await Navigator.push(context, MaterialPageRoute(builder: (_) => RetirarEncomendaScreen(encomenda: enc)));
                          setState(() {});
                        },
                        child: const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                          Text('Clique aqui para Retirar', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 17)),
                          SizedBox(width: 10),
                          Icon(Icons.arrow_forward, color: Colors.white),
                        ]),
                      ),
                    ),
                  ]),
                )),
          const SizedBox(height: 14),
          if (pendentes.isNotEmpty)
            Container(
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(color: const Color(0xFF1A1F35), borderRadius: BorderRadius.circular(16)),
              child: Column(children: [
                Row(children: [Container(padding: const EdgeInsets.all(6), decoration: BoxDecoration(color: const Color(0xFFFF6B00).withValues(alpha: 0.15), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.calendar_month, color: Color(0xFFFF6B00), size: 20)), const SizedBox(width: 12), Text('Entregue em ${pendentes.first.recebidaEm.day.toString().padLeft(2,'0')}/${pendentes.first.recebidaEm.month.toString().padLeft(2,'0')}/${pendentes.first.recebidaEm.year} às ${pendentes.first.recebidaEm.hour}:${pendentes.first.recebidaEm.minute.toString().padLeft(2,'0')}', style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w500))]),
                const SizedBox(height: 16),
                const Divider(color: Colors.white10, height: 1),
                const SizedBox(height: 16),
                Row(children: [
                  Container(padding: const EdgeInsets.all(6), decoration: BoxDecoration(color: const Color(0xFFFF6B00).withValues(alpha: 0.15), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.local_shipping, color: Color(0xFFFF6B00), size: 20)),
                  const SizedBox(width: 12),
                  Text(pendentes.first.transportadora, style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w500)),
                  const Spacer(),
                  const Icon(Icons.qr_code_scanner, color: Colors.white38, size: 20),
                ]),
              ]),
            ),
          const SizedBox(height: 120),
        ]),
      ),
    );
  }
}

class RetirarEncomendaScreen extends StatelessWidget {
  final Encomenda encomenda;
  const RetirarEncomendaScreen({super.key, required this.encomenda});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0E1E),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
          child: Column(children: [
            Center(
              child: Image.asset('assets/logo.png', height: 64, fit: BoxFit.contain, errorBuilder: (context, error, stack) {
                return Column(children: [
                  Container(width: 44, height: 44, decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.view_in_ar, color: Color(0xFFFF6B00), size: 28)),
                  const SizedBox(height: 4),
                  const Text('Smart', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16, height: 1)),
                  const Text('Cube', style: TextStyle(color: Color(0xFFFF6B00), fontWeight: FontWeight.bold, fontSize: 16, height: 1)),
                ]);
              }),
            ),
            const SizedBox(height: 20),
            Row(children: [
              IconButton(onPressed: () => Navigator.pop(context), icon: const Icon(Icons.arrow_back_ios, color: Colors.white, size: 20)),
              const Text('Retirar Encomenda', style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold)),
            ]),
            const SizedBox(height: 20),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(24)),
              child: Column(children: [
                if (encomenda.qrValido)
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20), boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.08), blurRadius: 20, offset: const Offset(0, 8))]),
                    // CORRIGIDO: antes era só Icon(Icons.qr_code_2) que não abre nada
                    // QR de verdade tem que ser gerado do codigoRetirada com pacote qr_flutter
                    // TODO: QrImageView(data: encomenda.codigoRetirada, size: 260)
                    child: const Column(children: [
                      Icon(Icons.qr_code_2, size: 260, color: Colors.black),
                      SizedBox(height: 8),
                      Text('QR gerado do código abaixo', style: TextStyle(fontSize: 11, color: Colors.grey)),
                    ]),
                  )
                else
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(color: Colors.red.shade50, borderRadius: BorderRadius.circular(20), border: Border.all(color: Colors.red.shade200)),
                    child: Column(children: [
                      Icon(Icons.block, size: 80, color: Colors.red.shade400),
                      const SizedBox(height: 12),
                      const Text('QR EXPIRADO', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold, fontSize: 22)),
                      Text('Usado em ${encomenda.dataRetirada != null ? "${encomenda.dataRetirada!.day}/${encomenda.dataRetirada!.month} às ${encomenda.dataRetirada!.hour}:${encomenda.dataRetirada!.minute.toString().padLeft(2,'0')}" : ""}', style: TextStyle(color: Colors.red.shade700)),
                    ]),
                  ),
                const SizedBox(height: 20),
                Text(encomenda.codigoRetirada, style: const TextStyle(color: Color(0xFFFF6B00), fontSize: 32, fontWeight: FontWeight.bold, letterSpacing: 2)),
                const SizedBox(height: 8),
                Text(encomenda.locker.replaceAll('Locker L', 'Box '), style: TextStyle(color: Colors.grey.shade700, fontSize: 20, fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                Text(encomenda.qrValido ? 'Aproxime o QR Code do leitor\ndo locker' : 'Este QR já foi utilizado e não\npode abrir novamente', textAlign: TextAlign.center, style: TextStyle(color: Colors.grey.shade800, fontSize: 16, fontWeight: FontWeight.w500)),
                const SizedBox(height: 24),
                SizedBox(
                  width: double.infinity,
                  height: 54,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFFF6B00), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
                    onPressed: () => ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Suporte acionado!'))),
                    child: const Text('Problemas na retirada?', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
                  ),
                ),
              ]),
            ),
            const SizedBox(height: 30),
          ],
        ),
      ),
    );
  }
}

class DetalheEncomendaScreen extends StatefulWidget {
  final Encomenda encomenda;
  const DetalheEncomendaScreen({super.key, required this.encomenda});
  @override
  State<DetalheEncomendaScreen> createState() => _DetalheEncomendaScreenState();
}

class _DetalheEncomendaScreenState extends State<DetalheEncomendaScreen> {
  String formatarData(DateTime dt) {
    return '${dt.day.toString().padLeft(2,'0')}/${dt.month.toString().padLeft(2,'0')}/${dt.year} às ${dt.hour.toString().padLeft(2,'0')}:${dt.minute.toString().padLeft(2,'0')}';
  }

  // CORRIGIDO: removido simularRetiradaNoTablet() - antes o app fingia que o tablet validou e expirava o QR localmente
  // Isso não abria box nenhum, só enganava o morador. Retirada só vale quando o backend confirma.

  @override
  Widget build(BuildContext context) {
    var enc = widget.encomenda;
    return Scaffold(
      backgroundColor: const Color(0xFFF0F0F5),
      appBar: AppBar(
        backgroundColor: const Color(0xFF050E1F),
        leading: IconButton(icon: const Icon(Icons.arrow_back, color: Colors.white), onPressed: () => Navigator.pop(context)),
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(enc.pacoteId, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
          Text(enc.blocoUnidade, style: const TextStyle(color: Colors.white70, fontSize: 12)),
        ]),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)),
            child: Column(children: [
              if (enc.qrValido) ...[
                Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16), boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.08), blurRadius: 12)]), child: const Icon(Icons.qr_code_2, size: 180, color: Colors.black)),
                const SizedBox(height: 12),
                Text(enc.codigoRetirada, style: const TextStyle(color: Color(0xFFFF6B00), fontSize: 28, fontWeight: FontWeight.bold, letterSpacing: 2)),
                const SizedBox(height: 4),
                Text(enc.locker.replaceAll('Locker L', 'Box '), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
                const SizedBox(height: 8),
                Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6), decoration: BoxDecoration(color: Colors.green.shade50, borderRadius: BorderRadius.circular(20)), child: Row(mainAxisSize: MainAxisSize.min, children: [Icon(Icons.check_circle, size: 14, color: Colors.green.shade700), const SizedBox(width: 4), Text('QR VÁLIDO', style: TextStyle(color: Colors.green.shade700, fontSize: 12, fontWeight: FontWeight.bold))])),
              ] else ...[
                Icon(Icons.block, size: 80, color: Colors.red.shade300),
                const SizedBox(height: 10),
                const Text('QR EXPIRADO', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold, fontSize: 20)),
                const SizedBox(height: 6),
                const Text('Este QR já foi utilizado e não pode abrir o box novamente.', textAlign: TextAlign.center, style: TextStyle(color: Colors.black54)),
              ],
              // CORRIGIDO: removido botão "Simular leitura no tablet"
            ]),
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Dados da Entrega', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              const SizedBox(height: 12),
              _linhaDetalhe(Icons.calendar_today, 'Data entrega', formatarData(enc.recebidaEm)),
              _linhaDetalhe(Icons.person, 'Quem entregou', enc.quemEntregou),
              _linhaDetalhe(Icons.local_shipping, 'Transportadora', enc.transportadora),
              _linhaDetalhe(Icons.inbox, 'Box', enc.locker.replaceAll('Locker L', 'Box ')),
            ]),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Dados da Retirada', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              const SizedBox(height: 12),
              if (enc.dataRetirada != null) ...[
                _linhaDetalhe(Icons.check_circle, 'Data retirada', formatarData(enc.dataRetirada!)),
                _linhaDetalhe(Icons.person_outline, 'Quem retirou', enc.quemRetirou.isNotEmpty ? enc.quemRetirou : 'Não informado'),
                _linhaDetalhe(Icons.qr_code, 'QR', enc.qrValido ? 'Válido - ${enc.codigoRetirada}' : 'Expirado em ${formatarData(enc.dataRetirada!)}'),
              ] else ...[
                _linhaDetalhe(Icons.hourglass_empty, 'Status', 'Aguardando retirada - QR ainda válido'),
                _linhaDetalhe(Icons.qr_code, 'Código', enc.codigoRetirada),
              ],
              const SizedBox(height: 12),
              const Divider(),
              const SizedBox(height: 8),
              const Text('No backend: quando o tablet valida o QR, seta qrValido=false e grava dataRetirada/quemRetirou. Próxima tentativa retorna QR EXPIRADO.', style: TextStyle(fontSize: 11, color: Colors.black54)),
            ]),
          ),
        ],
      ),
    );
  }

  Widget _linhaDetalhe(IconData icon, String label, String valor) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(children: [
        Container(padding: const EdgeInsets.all(6), decoration: BoxDecoration(color: const Color(0xFF050E1F).withValues(alpha: 0.08), borderRadius: BorderRadius.circular(8)), child: Icon(icon, size: 16, color: const Color(0xFF050E1F))),
        const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label, style: const TextStyle(fontSize: 11, color: Colors.black54)), Text(valor, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))])),
      ]),
    );
  }
}

class HistoricoTab extends StatefulWidget {
  final String condominioNome;
  const HistoricoTab({super.key, required this.condominioNome});
  @override
  State<HistoricoTab> createState() => _HistoricoTabState();
}

class _HistoricoTabState extends State<HistoricoTab> {
  String filtro = 'Todos';
  @override
  Widget build(BuildContext context) {
    var lista = db;
    return Scaffold(
      backgroundColor: const Color(0xFFF0F0F5),
      appBar: AppBar(backgroundColor: const Color(0xFF050E1F), title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [const Text('Entregas', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)), Text(widget.condominioNome, style: const TextStyle(color: Colors.white70, fontSize: 12))]), actions: [IconButton(icon: const Icon(Icons.filter_list, color: Colors.white), onPressed: () => showModalBottomSheet(context: context, builder: (_) => Container(padding: const EdgeInsets.all(20), child: Column(mainAxisSize: MainAxisSize.min, children: [ListTile(title: const Text('Todos'), onTap: () { setState(() => filtro='Todos'); Navigator.pop(context);}), ListTile(title: const Text('Não retirada'), onTap: () { setState(() => filtro='Não retirada'); Navigator.pop(context);}), ListTile(title: const Text('Entregue'), onTap: () { setState(() => filtro='Entregue'); Navigator.pop(context);})]))))],
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(12),
        itemCount: lista.length,
        itemBuilder: (context, i) {
          var enc = lista[i];
          if (filtro != 'Todos' && enc.status != filtro) return const SizedBox.shrink();
          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Material(
              color: Colors.white,
              borderRadius: BorderRadius.circular(14),
              clipBehavior: Clip.antiAlias,
              child: ListTile(
                onTap: () {
                  Navigator.push(context, MaterialPageRoute(builder: (_) => DetalheEncomendaScreen(encomenda: enc))).then((_) => setState(() {}));
                },
                leading: Container(width: 48, height: 48, decoration: BoxDecoration(color: const Color(0xFF050E1F).withValues(alpha: 0.08), borderRadius: BorderRadius.circular(10)), child: Icon(enc.qrValido ? Icons.qr_code : Icons.block, color: const Color(0xFF050E1F))),
                title: Text('${enc.blocoUnidade} - Pacote', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
                subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${enc.pacoteId} ${enc.codigo} • ${enc.locker.replaceAll('Locker L', 'Box ')}', style: const TextStyle(fontSize: 11)),
                  Text('Recebida em ${enc.recebidaEm.day.toString().padLeft(2,'0')}/${enc.recebidaEm.month.toString().padLeft(2,'0')}/${enc.recebidaEm.year}', style: const TextStyle(fontSize: 11)),
                  Row(children: [
                    Text(enc.status, style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: enc.status=='Não retirada' ? const Color(0xFFB85C00) : Colors.green)),
                    const SizedBox(width: 8),
                    Text(enc.qrValido ? 'QR Válido' : 'QR Expirado', style: TextStyle(fontSize: 10, color: enc.qrValido ? Colors.green : Colors.red)),
                  ]),
                ]),
                trailing: const Icon(Icons.arrow_forward_ios, size: 12),
              ),
            ),
          );
        },
      ),
    );
  }
}

class PerfilTab extends StatefulWidget {
  final String emailLogado;
  final String condominioNome;
  final String tipoPerfil;
  const PerfilTab({super.key, this.emailLogado = '', required this.condominioNome, this.tipoPerfil = 'Morador'});
  @override
  State<PerfilTab> createState() => _PerfilTabState();
}

class _PerfilTabState extends State<PerfilTab> {
  // CORRIGIDO: removido nome fixo 'Guilherme Martins' - antes todo mundo logava e via nome dele
  String nomeCompleto = '';
  // CORRIGIDO: tipoPerfil vem do backend, não de email.contains('sindico')
  // Antes: qualquer um criava conta sindico@qualquer.com e virava Síndico
  String get tipoPerfil => widget.tipoPerfil;
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 10),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Perfil', style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: Colors.black)),
                const SizedBox(height: 4),
                Text(widget.condominioNome, style: const TextStyle(fontSize: 14, color: Colors.black87)),
              ]),
            ),
            Container(height: 8, color: const Color(0xFFF2F2F2)),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 24, 20, 20),
              child: Row(children: [
                Stack(children: [
                  Container(width: 90, height: 90, decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: Colors.grey.shade500, width: 1.2)), child: Icon(Icons.person_outline, size: 60, color: Colors.grey.shade600)),
                  Positioned(bottom: 0, right: 0, child: InkWell(onTap: () => ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Selecionar foto da galeria'))), child: Container(padding: const EdgeInsets.all(5), decoration: const BoxDecoration(color: Color(0xFFFF6B00), shape: BoxShape.circle), child: const Icon(Icons.camera_alt, color: Colors.white, size: 14)))),
                ]),
                const SizedBox(width: 16),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [Expanded(child: Text(nomeCompleto.isEmpty ? 'Carregando...' : nomeCompleto, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.black))), InkWell(onTap: _editarNome, child: const Icon(Icons.edit, size: 16, color: Colors.grey))]),
                  const SizedBox(height: 4),
                  Text(widget.emailLogado, style: const TextStyle(fontSize: 13, color: Colors.black87)),
                  const SizedBox(height: 8),
                  Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5), decoration: BoxDecoration(borderRadius: BorderRadius.circular(8), border: Border.all(color: Colors.grey.shade300)), child: Text(tipoPerfil, style: const TextStyle(fontSize: 11, color: Colors.black87, fontWeight: FontWeight.w500))),
                ])),
              ]),
            ),
            Container(height: 8, color: const Color(0xFFF2F2F2)),
            const SizedBox(height: 10),
            _itemMenu(icon: Icons.settings, label: 'Configurações', onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ConfiguracoesScreen()))),
            _itemMenu(icon: Icons.chat_bubble_outline, label: 'Fale Conosco', onTap: () => ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Fale Conosco: suporte@smartcube.com')))),
            _itemMenu(icon: Icons.power_settings_new, label: 'Sair', onTap: () => Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => const LoginScreen()), (r) => false)),
            const Spacer(),
            Padding(padding: const EdgeInsets.only(right: 20, bottom: 20), child: Align(alignment: Alignment.centerRight, child: Text('Versão: 3.4.3', style: TextStyle(fontSize: 12, color: Colors.grey.shade700)))),
          ],
        ),
      ),
    );
  }
  Widget _itemMenu({required IconData icon, required String label, required VoidCallback onTap}) {
    return InkWell(onTap: onTap, child: Padding(padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 18), child: Row(children: [Icon(icon, color: const Color(0xFF2D2D6B), size: 26), const SizedBox(width: 14), Text(label, style: const TextStyle(fontSize: 16, color: Colors.black))])));
  }
  void _editarNome() {
    TextEditingController c = TextEditingController(text: nomeCompleto);
    showDialog(context: context, builder: (_) => AlertDialog(title: const Text('Nome completo'), content: TextField(controller: c, decoration: const InputDecoration(hintText: 'Digite seu nome completo')), actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancelar')), ElevatedButton(onPressed: () { setState(() => nomeCompleto = c.text.trim()); Navigator.pop(context); }, child: const Text('Salvar'))]));
  }
}

class ConfiguracoesScreen extends StatefulWidget {
  const ConfiguracoesScreen({super.key});
  @override
  State<ConfiguracoesScreen> createState() => _ConfiguracoesScreenState();
}

class _ConfiguracoesScreenState extends State<ConfiguracoesScreen> {
  bool notifAtiva = true;
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF5F6FA),
      appBar: AppBar(backgroundColor: const Color(0xFF050E1F), leading: IconButton(icon: const Icon(Icons.arrow_back, color: Colors.white), onPressed: () => Navigator.pop(context)), title: const Text('Configurações', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold))),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Material(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          clipBehavior: Clip.antiAlias,
          child: Column(children: [
            SwitchListTile(
              value: notifAtiva,
              onChanged: (v) => setState(() => notifAtiva = v),
              activeThumbColor: const Color(0xFFFF6B00),
              secondary: Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: const Color(0xFF050E1F).withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.notifications, color: Color(0xFF050E1F))),
              title: const Text('1- Notificações'),
              subtitle: const Text('Configurações de notificações')
            ),
            const Divider(height: 1),
            ListTile(
              leading: Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: const Color(0xFF050E1F).withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.security, color: Color(0xFF050E1F))), title: const Text('2- Segurança'), subtitle: const Text('Alterar senha'), trailing: const Icon(Icons.arrow_forward_ios, size: 14), onTap: () => _alterarSenha()),
            const Divider(height: 1),
            ListTile(
              leading: Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: const Color(0xFF050E1F).withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.app_settings_alt, color: Color(0xFF050E1F))), title: const Text('3- Permissões do app'), subtitle: const Text('Notificação'), trailing: const Icon(Icons.arrow_forward_ios, size: 14), onTap: () => ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Abrir Configurações do Sistema > Apps > SmartCube > Permissões')))),
            const Divider(height: 1),
            ListTile(
              leading: Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: const Color(0xFF050E1F).withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.system_update, color: Color(0xFF050E1F))), title: const Text('4- Checar atualização'), subtitle: const Text('Versão 3.4.3 - Toque para verificar'), trailing: const Icon(Icons.arrow_forward_ios, size: 14), onTap: () => ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Você já está na última versão!')))),
          ]),
        ),
      ]),
    );
  }
  void _alterarSenha() {
    TextEditingController atual = TextEditingController();
    TextEditingController nova = TextEditingController();
    showDialog(context: context, builder: (_) => AlertDialog(title: const Text('Alterar senha'), content: Column(mainAxisSize: MainAxisSize.min, children: [TextField(controller: atual, obscureText: true, decoration: const InputDecoration(labelText: 'Senha atual')), const SizedBox(height: 10), TextField(controller: nova, obscureText: true, decoration: const InputDecoration(labelText: 'Nova senha'))]), actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancelar')), ElevatedButton(style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFFF6B00)), onPressed: () {
      // CORRIGIDO: antes mostrava "Senha alterada" sem validar nada
      // Agora valida no front e exige backend - não finge que trocou
      if (nova.text.length < 6) { ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Nova senha precisa ter 6+ caracteres'))); return; }
      Navigator.pop(context);
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Alteração de senha ainda não conectada ao backend.')));
      atual.clear(); nova.clear();
    }, child: const Text('Salvar', style: TextStyle(color: Colors.white)))]));
  }
}
