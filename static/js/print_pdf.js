// Este script abre el PDF en una nueva pestaña y lanza la impresión automática
function printPDF(pdfUrl) {
    const win = window.open(pdfUrl, '_blank');
    if (!win) return alert('Permite las ventanas emergentes para imprimir el PDF.');
    win.onload = function() {
        setTimeout(() => {
            win.print();
        }, 500); // Espera a que cargue el PDF
    };
}
