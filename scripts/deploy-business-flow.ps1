# Upload product flow page to hugme2.com (nginx static)
$LocalFile = Join-Path $PSScriptRoot "..\docs\product\business-flow.html"
$Key = "$env:USERPROFILE\.ssh\eris_67.216.204.137"
$Remote = "root@67.216.204.137:/usr/share/nginx/html/business-flow.html"
scp -i $Key -o IdentitiesOnly=yes -P 2222 $LocalFile $Remote
